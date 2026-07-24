"""Manual maintenance services (phase 1.8.2).

Two operator-driven, manual-only maintenance actions. NEITHER runs on a timer —
phase 1.8.2 is explicitly manual cleanup, not automatic retention.

1. :func:`cleanup_terminal_data` — delete OLD TERMINAL task data (tasks +
   their executions + log index rows + the on-disk log bodies + their
   command-outbox rows). It never touches a queued/running/finalizing task. A
   ``dry_run`` computes the would-delete counts without mutating anything.

2. :func:`mark_task_lost` — manually mark a STUCK ACTIVE task ``lost`` (its
   non-terminal executions become ``lost`` with a manual reason). It NEVER
   hard-deletes active data; it reuses the same soft-terminal ``lost`` semantics
   as the reconcile loop (:func:`dopilot_server.redis.reconcile.mark_lost`), so a
   late agent-authoritative terminal can still override it.

Naming (phase 2a clean-cut): the log index + command outbox key on ``task_id``
(= the parent :class:`Task` id) and ``execution_id`` (= the atomic
:class:`Execution` id). The queries below filter on ``task_id``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from dopilot_protocol.streams import EVENT_STREAM, LOG_STREAM
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..logs import files
from ..models.command_outbox import CommandOutbox
from ..models.event_audit import EventAudit
from ..models.execution import Execution, ExecutionLogFile, Task
from ..redis import reconcile
from ..redis.client import RedisStreamClient
from . import executions as svc
from . import states

log = logging.getLogger(__name__)

# Reason recorded on manually lost executions/tasks (audit in error/status detail).
MANUAL_LOST_REASON = "manual_cleanup"


@dataclass
class CleanupSummary:
    """Counts deleted (or, for a dry run, that WOULD be deleted)."""

    dry_run: bool
    cutoff: str
    tasks: int = 0
    executions: int = 0
    log_files: int = 0
    log_files_removed: int = 0
    log_bytes: int = 0
    command_outbox: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarkLostSummary:
    task_id: str
    task_status: str
    executions_marked: int = 0
    already_terminal: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _terminal_before(cutoff: datetime):
    """SQL predicate: a TERMINAL task whose effective time is before ``cutoff``.

    Effective time is ``finished_at`` when present, else ``created_at`` (a
    conservative fallback for terminal rows that never recorded a finish time).
    """
    return (
        Task.status.in_(tuple(states.TASK_TERMINAL)),
        or_(
            Task.finished_at < cutoff,
            (Task.finished_at.is_(None)) & (Task.created_at < cutoff),
        ),
    )


async def cleanup_terminal_data(
    session: AsyncSession,
    settings: Settings,
    *,
    cutoff: datetime,
    dry_run: bool = False,
) -> CleanupSummary:
    """Delete terminal task data older than ``cutoff`` — failure-safe.

    Used by BOTH the manual maintenance API and the automatic retention sweep
    (:class:`RetentionSweepLoop`). Because the automatic sweep runs unattended, the
    deletion is ordered so an interruption can NEVER leave a live index row
    pointing at an already-deleted body (which would be an unmarked dangling
    index, violating the "log gaps are visible audit facts" invariant):

    STEP 1 — mark every matching ``execution_log_files`` row ``status='expired'``
      and **commit**. Once committed, an absent body is an explicit, auditable
      state (``expired``), not silent corruption.
    STEP 2 — unlink the on-disk bodies (offloaded so the blocking unlink/rmdir
      never runs on the event loop). A missing file is idempotent; a real unlink
      failure is logged and the row is left for the next sweep to retry.
    STEP 3 — delete the rows in FK-safe order (``execution_log_files`` ->
      ``executions`` -> ``command_outbox`` -> ``tasks``) and **commit**.

    A crash between any steps leaves expired-marked rows; the next sweep re-selects
    them (still terminal + old) and idempotently completes the deletion. Only
    terminal tasks are eligible, so a queued/running/finalizing task is never
    touched. ``dry_run`` returns the counts without mutating, unlinking, or
    committing anything (and is what the manual API preview uses).

    Unlike the pre-resource-caps version, this function OWNS its commits when not
    ``dry_run`` (it must, for the two-phase safety); callers no longer commit.
    """
    summary = CleanupSummary(dry_run=dry_run, cutoff=cutoff.isoformat())

    task_rows = (
        await session.execute(select(Task.id).where(*_terminal_before(cutoff)))
    ).all()
    task_ids = [tid for (tid,) in task_rows]
    if not task_ids:
        return summary
    summary.tasks = len(task_ids)

    # Child executions (FK -> tasks.id). Counted for the summary; deleted below.
    exec_rows = (
        await session.execute(
            select(Execution.id).where(Execution.task_id.in_(task_ids))
        )
    ).all()
    summary.executions = len(exec_rows)

    # Log index rows keyed by task_id.
    log_files = (
        (
            await session.execute(
                select(ExecutionLogFile).where(
                    ExecutionLogFile.task_id.in_(task_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    summary.log_files = len(log_files)
    summary.log_bytes = sum(int(lf.size_bytes or 0) for lf in log_files)

    # Command-outbox rows keyed by task_id. Safe to drop wholesale — the parent
    # task is terminal, so none of its commands are still in flight.
    outbox_rows = (
        await session.execute(
            select(CommandOutbox.command_id).where(
                CommandOutbox.task_id.in_(task_ids)
            )
        )
    ).all()
    summary.command_outbox = len(outbox_rows)

    if dry_run:
        return summary

    # STEP 1: mark bodies expired + commit BEFORE any unlink (audit fact first).
    await session.execute(
        update(ExecutionLogFile)
        .where(ExecutionLogFile.task_id.in_(task_ids))
        .values(status=states.LOG_EXPIRED, log_integrity=states.LOG_EXPIRED)
    )
    await session.commit()

    # STEP 2: unlink bodies. A body that could NOT be removed (permission error,
    # or a hard OSError) leaves its task OUT of the row deletion below, so the
    # expired row keeps pointing at the still-present file and the next sweep
    # retries the unlink. Never delete an index whose body still exists — that
    # would orphan the file forever (R-03). A missing file is idempotent success.
    failed_task_ids: set[str] = set()
    for lf in log_files:
        try:
            if await files.aremove(lf.storage_path):
                summary.log_files_removed += 1
                continue
        except OSError:
            log.error(
                "retention: error unlinking log body %s (retry next sweep)",
                lf.storage_path, exc_info=True,
            )
            failed_task_ids.add(lf.task_id)
            continue
        # aremove returned False: either already-gone (ok to delete the row) or
        # the file still exists (removal failed silently — must NOT delete the row).
        if await files.aexists(lf.storage_path):
            log.error(
                "retention: could not unlink log body %s (retry next sweep)",
                lf.storage_path,
            )
            failed_task_ids.add(lf.task_id)

    # STEP 3: delete only tasks whose bodies are fully gone, FK-safe + commit.
    # Tasks with a failed unlink stay (rows expired, retried next sweep).
    deletable = [tid for tid in task_ids if tid not in failed_task_ids]
    if deletable:
        await session.execute(
            delete(ExecutionLogFile).where(
                ExecutionLogFile.task_id.in_(deletable)
            )
        )
        await session.execute(
            delete(Execution).where(Execution.task_id.in_(deletable))
        )
        await session.execute(
            delete(CommandOutbox).where(CommandOutbox.task_id.in_(deletable))
        )
        await session.execute(delete(Task).where(Task.id.in_(deletable)))
    await session.commit()
    summary.tasks = len(deletable)
    return summary


async def prune_event_audit(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime,
) -> int:
    """Delete ``event_audit`` rows older than the configured window (B3).

    ``event_audit`` grows by one row per consumed agent status event (the
    fastest-growing table) and had no cleanup path before the resource caps. Rows
    older than ``maintenance.event_audit_retention_days`` are deleted in bounded
    batches (``event_audit_delete_batch``), COMMITTING per batch so a large
    backlog never holds a long table lock. Returns the number of rows deleted.
    A retention of 0 disables pruning.
    """
    days = settings.maintenance.event_audit_retention_days
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    batch = max(1, settings.maintenance.event_audit_delete_batch)
    total = 0
    while True:
        ids = (
            await session.execute(
                select(EventAudit.id)
                .where(EventAudit.processed_at < cutoff)
                .limit(batch)
            )
        ).scalars().all()
        if not ids:
            break
        await session.execute(
            delete(EventAudit).where(EventAudit.id.in_(ids))
        )
        await session.commit()
        total += len(ids)
        if len(ids) < batch:
            break
    return total


async def trim_log_streams(
    redis_client: RedisStreamClient | None,
    settings: Settings,
    *,
    now: datetime,
) -> dict[str, int]:
    """Time-trim the Redis log + event streams via ``XTRIM MINID`` (B4).

    Implements the previously-inert ``redis.log_retention_seconds``: entries
    older than the window are trimmed regardless of the per-XADD MAXLEN (the
    primary bound). ``minid`` is the millisecond epoch of ``now - retention`` —
    Redis stream ids are ``<ms>-<seq>``, so this drops every entry produced before
    that instant. A per-stream failure is logged and skipped (never aborts the
    sweep). Returns a map of stream -> entries trimmed. Retention 0 (or no client)
    disables the time trim.
    """
    seconds = settings.redis.log_retention_seconds
    if seconds <= 0 or redis_client is None:
        return {}
    minid = int((now.timestamp() - seconds) * 1000)
    if minid <= 0:
        return {}
    trimmed: dict[str, int] = {}
    for stream in (LOG_STREAM, EVENT_STREAM):
        try:
            trimmed[stream] = await redis_client.xtrim(
                stream, minid=minid, approximate=True
            )
        except Exception:  # noqa: BLE001 - one bad stream never aborts the sweep
            log.error(
                "retention: XTRIM %s MINID %s failed", stream, minid,
                exc_info=True,
            )
    return trimmed


async def mark_task_lost(
    session: AsyncSession, task: Task
) -> MarkLostSummary:
    """Manually mark a STUCK ACTIVE task (+ its active executions) ``lost``.

    Eligible only when the task is active (queued/running/finalizing). Active
    executions become ``lost`` with reason :data:`MANUAL_LOST_REASON` via the
    shared :func:`reconcile.mark_lost` (soft terminal, overridable by a later
    agent-authoritative terminal). The task is rolled up / forced to ``lost`` and
    the audit is recorded in ``status_reason`` / ``status_detail``. NEVER deletes.
    """
    if task.status not in states.TASK_ACTIVE:
        raise ApiError(
            409,
            "task.not_active",
            "errors.taskNotActive",
            {"task_id": task.id, "status": task.status},
        )

    now = datetime.now(UTC)
    summary = MarkLostSummary(task_id=task.id, task_status=task.status)
    executions = await svc.list_executions(session, task.id)
    for execution in executions:
        if execution.status in states.EXEC_TERMINAL:
            summary.already_terminal.append(execution.id)
            continue
        if await reconcile.mark_lost(session, execution, MANUAL_LOST_REASON, now):
            summary.executions_marked += 1

    # reconcile.mark_lost rolls the task up when every execution is terminal; for
    # the zero-execution / not-yet-rolled case, force the active task to lost
    # (queued/running/finalizing -> lost is a valid transition).
    if task.status in states.TASK_ACTIVE and states.is_valid_task_transition(
        task.status, states.TASK_LOST
    ):
        task.status = states.TASK_LOST
        task.finished_at = now

    if task.status == states.TASK_LOST:
        task.status_reason = MANUAL_LOST_REASON
        task.status_detail = {
            "reason": MANUAL_LOST_REASON,
            "executions_marked": summary.executions_marked,
            "marked_at": now.isoformat(),
        }
    summary.task_status = task.status
    return summary
