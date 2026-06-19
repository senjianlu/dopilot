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


def _gap_marker(expected: int, actual: int) -> bytes:
    return (
        f"\n[dopilot:log-gap expected_offset={expected} "
        f"actual_offset={actual}]\n"
    ).encode()


async def apply_log_event(
    session: AsyncSession,
    settings: Settings,
    event: AgentLogEvent,
    manager: SubscriptionManager | None = None,
) -> str:
    """Apply one log increment; returns an outcome string. Caller commits."""
    log_file = await svc.get_log_file(
        session, event.execution_id, event.attempt_id, event.stream.value
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

    physical_start = files.size(log_file.storage_path)
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
        files.append(log_file.storage_path, marker)

    # write bytes to disk BEFORE advancing the DB offset (at-most-a-duplicate)
    files.append(log_file.storage_path, raw)
    log_file.last_pulled_offset = event.offset + event.size_bytes
    log_file.size_bytes = files.size(log_file.storage_path)
    log_file.final_offset = log_file.size_bytes

    if manager is not None:
        # The SSE content spans EXACTLY [physical_start, physical_end] — it
        # includes the gap marker so the web's offset tracking stays consistent
        # with the on-disk physical bytes (the marker is meant to be visible).
        # SSE is a TEXT channel for human display, so bytes are decoded with
        # errors="replace" here; byte-fidelity lives on disk (written above) and
        # in the file-backed snapshot/download path, not in the live SSE stream.
        manager.publish(
            event.execution_id,
            {
                "type": "log",
                "start_offset": physical_start,
                "end_offset": log_file.size_bytes,
                "content": (marker + raw).decode("utf-8", errors="replace"),
            },
        )
    return outcome
