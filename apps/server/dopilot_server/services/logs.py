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

import asyncio
import base64
import logging
import os

from dopilot_protocol import AgentLogEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..logs import files
from ..logs.dir_gauge import LogsDirGauge, file_size
from ..logs.sse import SubscriptionManager
from ..models.notification import SEVERITY_WARNING, TYPE_LOG_TRUNCATED
from ..services import executions as svc
from ..services import notifications as notif
from ..services import outbox as outbox_svc
from .states import LOG_ACTIVE, LOG_FINALIZING

logger = logging.getLogger(__name__)

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
# Log-flood guard: the log file is no longer writable (sealed by the outcome
# recorder / finalize, expired by cleanup, or missing) -> the increment is
# discarded without touching disk or integrity (still consumed + ACKed).
OUTCOME_SEALED = "sealed"

# Sticky log_integrity value once a file hits its size cap (see LogsSettings
# .max_file_bytes). Decoupled from lifecycle status, like "partial".
INTEGRITY_TRUNCATED = "truncated"
TRUNCATION_SIZE_CAP = "size-cap"
TRUNCATION_DIR_BUDGET = "dir-budget"
TRUNCATION_MAINTENANCE = "maintenance"

#: Log-file lifecycle states that still accept increments.
WRITABLE_LOG_STATUSES = frozenset({LOG_ACTIVE, LOG_FINALIZING})


def _gap_marker(expected: int, actual: int) -> bytes:
    return (
        f"\n[dopilot:log-gap expected_offset={expected} "
        f"actual_offset={actual}]\n"
    ).encode()


def _truncation_marker(max_bytes: int, reason: str = TRUNCATION_SIZE_CAP) -> bytes:
    return (
        f"\n[dopilot:log-truncated max_bytes={max_bytes} "
        f"reason={reason}]\n"
    ).encode()


def _plan_write(
    physical_start: int, payload: bytes, cap: int, gauge: LogsDirGauge | None
) -> tuple[bytes, bool, str | None]:
    """Decide exactly what will be written (log-flood guard, gates 3a/3b).

    Returns ``(to_write, truncated_now, reason)``. Per-file cap first (body
    prefix + size-cap marker), then the logs-dir budget: when even the planned
    bytes do not fit, the body is dropped and only a dir-budget marker is written
    — and only if THAT fits; otherwise nothing at all is written (DB state only).
    """
    to_write = payload
    truncated_now = False
    reason: str | None = None
    if cap > 0:
        room = cap - physical_start
        if len(payload) > room:
            to_write = payload[: max(0, room)] + _truncation_marker(cap, TRUNCATION_SIZE_CAP)
            truncated_now = True
            reason = TRUNCATION_SIZE_CAP
    if gauge is not None and gauge.budget > 0 and not gauge.fits(len(to_write)):
        marker = _truncation_marker(gauge.budget, TRUNCATION_DIR_BUDGET)
        to_write = marker if gauge.fits(len(marker)) else b""
        truncated_now = True
        reason = TRUNCATION_DIR_BUDGET
    return to_write, truncated_now, reason


def _write_settled(path: str, data: bytes, gauge: LogsDirGauge | None) -> tuple[int, int]:
    """Append ``data`` and settle the gauge from before/after ``stat`` (thread).

    Whatever physically landed — including a partial write before an
    ENOSPC / flush failure — is what the gauge learns; the exception is re-raised
    after settling so the consumer retries the message.
    """
    before = file_size(path)
    try:
        if data:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "ab") as fh:
                fh.write(data)
    finally:
        after = file_size(path)
        if gauge is not None:
            gauge.add(after - before)
    return before, after


async def apply_log_event(
    session: AsyncSession,
    settings: Settings,
    event: AgentLogEvent,
    manager: SubscriptionManager | None = None,
    gauge: LogsDirGauge | None = None,
) -> str:
    """Apply one log increment; returns an outcome string. Caller commits.

    Log-flood guard additions: the ``execution_log_files`` row is locked
    (``FOR UPDATE``) for the whole apply so the outcome recorder's seal and
    retention's truncate/evict serialise with it; increments for a file that is
    no longer writable are discarded (``sealed``); the logs-dir budget is an
    admission hard limit (``gauge``); hitting either cap queues a ``stop_logs``
    backpressure command and a ``log_truncated`` notification.
    """
    log_file = await svc.get_log_file(
        session, event.task_id, event.execution_id, event.stream.value, for_update=True
    )
    if log_file is None:
        return OUTCOME_NO_LOG_FILE

    if event.eof and event.size_bytes == 0:
        # eof is an optimization signal only; the bounded drain finalizes logs.
        return OUTCOME_EOF

    raw = base64.b64decode(event.content_b64) if event.content_b64 else b""
    if not raw:
        return OUTCOME_EOF if event.eof else OUTCOME_DROPPED_DUP

    if log_file.status not in WRITABLE_LOG_STATUSES:
        # Sealed / expired / missing: never write, never recreate, never change
        # integrity — the recorded outcome must not move after the fact.
        return OUTCOME_SEALED

    if event.offset < log_file.last_pulled_offset:
        return OUTCOME_DROPPED_DUP

    cap = settings.logs.max_file_bytes
    # Resource caps (B1): once a file is sticky-"truncated" we keep consuming and
    # ACKing the stream (never stall) but write no more body bytes — just advance
    # the agent cursor so offsets stay consistent and the marker stays one line.
    if log_file.log_integrity == INTEGRITY_TRUNCATED and (cap > 0 or gauge is not None):
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

    payload = marker + raw if (marker and raw) else (marker or raw)
    path = log_file.storage_path

    # Plan + write + settle the gauge under the ONE directory lock (no other
    # dopilot writer, calibration or deletion can interleave). The blocking
    # stat/write stays off the event loop; bytes hit disk BEFORE the DB offset
    # advances (at-most-a-duplicate).
    if gauge is not None:
        async with gauge.writer():
            physical_start = await files.asize(path)
            to_write, truncated_now, reason = _plan_write(physical_start, payload, cap, gauge)
            _before, physical_end = await asyncio.to_thread(_write_settled, path, to_write, gauge)
    else:
        physical_start = await files.asize(path)
        to_write, truncated_now, reason = _plan_write(physical_start, payload, cap, None)
        _before, physical_end = await asyncio.to_thread(_write_settled, path, to_write, None)

    log_file.last_pulled_offset = event.offset + event.size_bytes
    log_file.size_bytes = physical_end
    log_file.final_offset = physical_end
    if truncated_now:
        # Sticky: once truncated it never reverts (like "partial"). Overrides a
        # prior "partial" — truncated already implies incompleteness.
        log_file.log_integrity = INTEGRITY_TRUNCATED
        log_file.truncation_reason = reason
        outcome = OUTCOME_TRUNCATED
        await _on_truncated(session, settings, event, reason or TRUNCATION_SIZE_CAP, physical_end)

    if manager is not None and to_write:
        # The SSE content spans EXACTLY [physical_start, physical_end] — it
        # includes the gap marker so the web's offset tracking stays consistent
        # with the on-disk physical bytes (the marker is meant to be visible).
        # When this increment crossed a cap, only the bytes that were actually
        # written are published, so the SSE span still matches the physical
        # file. SSE is a TEXT channel for human display, so bytes are decoded
        # with errors="replace" here; byte-fidelity lives on disk.
        manager.publish(
            event.execution_id,
            {
                "type": "log",
                "start_offset": physical_start,
                "end_offset": physical_end,
                "content": to_write.decode("utf-8", errors="replace"),
            },
        )
    return outcome


async def _on_truncated(
    session: AsyncSession,
    settings: Settings,
    event: AgentLogEvent,
    reason: str,
    physical_end: int,
) -> None:
    """Backpressure + alert when a log file hits a cap (log-flood guard)."""
    try:
        await outbox_svc.create_stop_logs_outbox(
            session,
            task_id=event.task_id,
            execution_id=event.execution_id,
            agent_id=event.agent_id,
        )
    except Exception:  # noqa: BLE001 - backpressure is best-effort
        logger.warning("stop_logs enqueue failed for %s", event.execution_id, exc_info=True)
    payload = {
        "task_id": event.task_id,
        "execution_id": event.execution_id,
        "agent_id": event.agent_id,
        "reason": reason,
        "cap": settings.logs.max_file_bytes
        if reason == TRUNCATION_SIZE_CAP
        else settings.logs.max_total_bytes,
        "size_bytes": physical_end,
    }
    try:
        await notif.notify(
            session,
            type=TYPE_LOG_TRUNCATED,
            severity=SEVERITY_WARNING,
            payload=payload,
            dedupe_key=event.execution_id,
        )
    except Exception:  # noqa: BLE001 - alerting must never break consumption
        logger.warning("log_truncated notify failed for %s", event.execution_id, exc_info=True)
