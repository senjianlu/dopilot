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

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..logs import files
from ..models.command_outbox import CommandOutbox
from ..models.execution import Execution, ExecutionLogFile, Task
from ..redis import reconcile
from . import executions as svc
from . import states

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
    """Delete terminal task data older than ``cutoff``. Caller commits.

    Deletes, in FK-safe application order (there are no DB cascades): on-disk log
    bodies -> ``execution_log_files`` rows -> ``executions`` -> ``command_outbox``
    rows -> ``tasks``. Only terminal tasks are eligible, so a queued/running/
    finalizing task is never deleted. ``dry_run`` returns the counts without
    deleting or unlinking anything.
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

    # 1) on-disk log bodies (before the index rows that point at them).
    for lf in log_files:
        if files.remove(lf.storage_path):
            summary.log_files_removed += 1

    # 2) log index, 3) executions, 4) outbox, 5) tasks — FK-safe order.
    await session.execute(
        delete(ExecutionLogFile).where(
            ExecutionLogFile.task_id.in_(task_ids)
        )
    )
    await session.execute(
        delete(Execution).where(Execution.task_id.in_(task_ids))
    )
    await session.execute(
        delete(CommandOutbox).where(CommandOutbox.task_id.in_(task_ids))
    )
    await session.execute(delete(Task).where(Task.id.in_(task_ids)))
    return summary


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
