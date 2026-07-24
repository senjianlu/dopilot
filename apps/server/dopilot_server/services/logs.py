"""Server-side log-increment application (phase 1.5).

Applies one :class:`AgentLogEvent` to its ``execution_log_files`` row + on-disk
body + SSE fan-out, REPLACING the phase-1 HTTP tail pull. Offset rules
(refactor/00 §日志 offset), processed serially per attempt by the single log
consumer:

- ``offset < last_pulled_offset``  -> duplicate slice, dropped;
- ``offset == last_pulled_offset`` -> contiguous, appended; advance offset;
- ``offset > last_pulled_offset``   -> GAP: integrity becomes sticky ``partial``,
  a visible gap marker is written, the slice is appended, and the offset jumps
  to ``offset + size_bytes`` (the agent logical end). Gaps never block the
  execution from reaching a terminal.

``last_pulled_offset`` = agent logical byte progress; ``final_offset`` /
``size_bytes`` = server file PHYSICAL size (including gap markers). The two are
never mixed. Bytes hit disk BEFORE the DB offset advances (at-most-a-duplicate).
"""

from __future__ import annotations

import base64

from dopilot_protocol import AgentLogEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..logs import files
from ..logs.sse import SubscriptionManager
from ..services import executions as svc

OUTCOME_APPENDED = "appended"
OUTCOME_DROPPED_DUP = "dropped_dup"
OUTCOME_GAP_PARTIAL = "gap_partial"
OUTCOME_EOF = "eof"
OUTCOME_NO_LOG_FILE = "no_log_file"
# Resource caps (B1): the file just reached its size cap on this increment (a
# truncation marker was written, log_integrity became sticky "truncated"), or it
# was already capped and this increment's bytes were dropped while the stream
# kept being consumed/ACKed.
OUTCOME_TRUNCATED = "truncated"
OUTCOME_TRUNCATED_DROPPED = "truncated_dropped"

# Sticky log_integrity value once a file hits its size cap (see LogsSettings
# .max_file_bytes). Decoupled from lifecycle status, like "partial".
INTEGRITY_TRUNCATED = "truncated"


def _gap_marker(expected: int, actual: int) -> bytes:
    return (
        f"\n[dopilot:log-gap expected_offset={expected} "
        f"actual_offset={actual}]\n"
    ).encode()


def _truncation_marker(max_bytes: int) -> bytes:
    return (
        f"\n[dopilot:log-truncated max_bytes={max_bytes} "
        f"reason=size-cap]\n"
    ).encode()


async def apply_log_event(
    session: AsyncSession,
    settings: Settings,
    event: AgentLogEvent,
    manager: SubscriptionManager | None = None,
) -> str:
    """Apply one log increment; returns an outcome string. Caller commits."""
    log_file = await svc.get_log_file(
        session, event.task_id, event.execution_id, event.stream.value
    )
    if log_file is None:
        return OUTCOME_NO_LOG_FILE

    if event.eof and event.size_bytes == 0:
        # eof is an optimization signal only; the bounded drain finalizes logs.
        return OUTCOME_EOF

    raw = base64.b64decode(event.content_b64) if event.content_b64 else b""
    if not raw:
        return OUTCOME_EOF if event.eof else OUTCOME_DROPPED_DUP

    if event.offset < log_file.last_pulled_offset:
        return OUTCOME_DROPPED_DUP

    cap = settings.logs.max_file_bytes
    # Resource caps (B1): once a file is sticky-"truncated" we keep consuming and
    # ACKing the stream (never stall) but write no more body bytes — just advance
    # the agent cursor so offsets stay consistent and the marker stays one line.
    if cap > 0 and log_file.log_integrity == INTEGRITY_TRUNCATED:
        log_file.last_pulled_offset = event.offset + event.size_bytes
        return OUTCOME_TRUNCATED_DROPPED

    outcome = OUTCOME_APPENDED
    marker = b""

    if event.offset > log_file.last_pulled_offset:
        # GAP: sticky partial + a visible marker prefixing the current slice.
        outcome = OUTCOME_GAP_PARTIAL
        log_file.log_integrity = "partial"
        log_file.gap_count = (log_file.gap_count or 0) + 1
        if log_file.first_gap_expected_offset is None:
            log_file.first_gap_expected_offset = log_file.last_pulled_offset
            log_file.first_gap_actual_offset = event.offset
        marker = _gap_marker(log_file.last_pulled_offset, event.offset)

    # Write marker+raw to disk in ONE offloaded thread hop BEFORE advancing the
    # DB offset (at-most-a-duplicate). The blocking open/write/getsize stays off
    # the event loop; ``physical_start``/``physical_end`` span exactly the bytes
    # written. Race-free because the single log consumer serializes writes (see
    # files.append_increment's single-writer invariant). The capped writer stops
    # the body at ``max_file_bytes`` (+ one truncation marker); ``last_pulled_offset``
    # still advances by the full agent range so the cursor never desyncs.
    physical_start, physical_end, truncated_now = (
        await files.aappend_increment_capped(
            log_file.storage_path, marker, raw, cap, _truncation_marker(cap)
        )
    )
    log_file.last_pulled_offset = event.offset + event.size_bytes
    log_file.size_bytes = physical_end
    log_file.final_offset = physical_end
    if truncated_now:
        # Sticky: once truncated it never reverts (like "partial"). Overrides a
        # prior "partial" — truncated already implies incompleteness.
        log_file.log_integrity = INTEGRITY_TRUNCATED
        outcome = OUTCOME_TRUNCATED

    if manager is not None:
        # The SSE content spans EXACTLY [physical_start, physical_end] — it
        # includes the gap marker so the web's offset tracking stays consistent
        # with the on-disk physical bytes (the marker is meant to be visible).
        # When this increment crossed the size cap, only the bytes that were
        # actually written (the fitted body prefix + the one truncation marker)
        # are published, so the SSE span still matches the physical file. SSE is a
        # TEXT channel for human display, so bytes are decoded with
        # errors="replace" here; byte-fidelity lives on disk (written above) and
        # in the file-backed snapshot/download path, not in the live SSE stream.
        if truncated_now:
            room = max(0, cap - physical_start)
            written = (marker + raw)[:room] + _truncation_marker(cap)
        else:
            written = marker + raw
        manager.publish(
            event.execution_id,
            {
                "type": "log",
                "start_offset": physical_start,
                "end_offset": physical_end,
                "content": written.decode("utf-8", errors="replace"),
            },
        )
    return outcome
