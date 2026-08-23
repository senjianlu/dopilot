"""Task outcome recorder (log-flood guard / schedule auto-disable).

The SINGLE, idempotent commit point that decides whether a terminal task was
erroneous and feeds the schedule's consecutive-error run. It is a poll (run by
``RedisReconcileLoop`` right after ``finalize_drained_logs``), not a hook, so
EVERY terminal write path — event rollup, dispatch timeout, reconcile /
maintenance ``mark_lost``, cancel — is covered without being instrumented.

Per candidate task (``status`` terminal, ``outcome_recorded_at IS NULL``),
processed in ``(finished_at, id)`` order:

1. lock ``task`` -> its ``executions`` -> its ``execution_log_files`` ->
   (later) the ``schedule`` row, all ``FOR UPDATE``, and RE-READ everything
   under the lock (a concurrent LogConsumer truncation either committed before
   — we see it — or waits for our commit and is then rejected as ``sealed``);
2. wait for the log files to be finalised by the drain (``status`` no longer
   active/finalizing) unless the drain window + 60s has passed (bounded
   fallback); ``lost`` tasks additionally wait for reclaim + drain or the
   ``lost_outcome_grace_seconds`` fallback (a pure server-lost stays open: the
   agent may still override it);
3. SEAL the log files (``complete`` + ``final_offset``) so no later increment
   can change their integrity, judge ``task_is_erroneous`` (including the
   agent-reported ``log_bytes`` vs the cap) and stamp the task;
4. if the task came from a schedule: upsert its row in
   ``schedule_outcome_ledger`` (by ``task_id``, so a corrected soft-lost
   updates in place), self-trim the ledger, RECOMPUTE the schedule's
   consecutive-error count from the ledger (current generation, newest first)
   and auto-disable at the threshold (one-way; manual re-enable bumps the
   generation).

Returns the ids of schedules it disabled so the caller can ``reload()`` the
APScheduler runner AFTER committing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..models.execution import Execution, ExecutionLogFile, Task
from ..models.notification import SEVERITY_ERROR, TYPE_SCHEDULE_AUTO_DISABLED
from ..models.scheduling import Schedule, ScheduleOutcomeLedger
from . import notifications as notif
from . import outbox as outbox_svc
from . import states
from .states import LOG_ACTIVE, LOG_COMPLETE, LOG_FINALIZING, TASK_LOST, TASK_TERMINAL

logger = logging.getLogger(__name__)

#: Bounded wait after the drain window before a task is recorded regardless.
FALLBACK_GRACE_SECONDS = 60
#: Task sources whose outcomes feed the schedule's consecutive-error run.
COUNTED_SOURCES = frozenset({states.TASK_SOURCE_TIMER, states.TASK_SOURCE_TRIGGER_NOW})
#: Ledger rows kept per schedule (at least this many, or 2x the threshold).
LEDGER_MIN_KEEP = 100


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _candidates(session: AsyncSession, limit: int) -> list[str]:
    rows = await session.execute(
        select(Task.id)
        .where(Task.status.in_(tuple(TASK_TERMINAL)), Task.outcome_recorded_at.is_(None))
        .order_by(Task.finished_at.asc().nulls_first(), Task.id.asc())
        .limit(limit)
    )
    return [r[0] for r in rows.all()]


async def _lock_task_graph(
    session: AsyncSession, task_id: str
) -> tuple[Task | None, list[Execution], dict[str, ExecutionLogFile], list[ExecutionLogFile]]:
    task = (
        await session.execute(
            select(Task)
            .where(Task.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if task is None:
        return None, [], {}, []
    executions = list(
        (
            await session.execute(
                select(Execution)
                .where(Execution.task_id == task_id)
                .order_by(Execution.created_at.asc(), Execution.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    )
    log_files = list(
        (
            await session.execute(
                select(ExecutionLogFile)
                .where(ExecutionLogFile.task_id == task_id)
                .order_by(ExecutionLogFile.execution_id.asc(), ExecutionLogFile.stream.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    )
    by_exec = {lf.execution_id: lf for lf in log_files if lf.stream == "log"}
    return task, executions, by_exec, log_files


async def _ready(
    session: AsyncSession,
    settings: Settings,
    task: Task,
    executions: list[Execution],
    log_files: list[ExecutionLogFile],
    now: datetime,
) -> bool:
    """May this task's outcome be recorded now? (see module docstring §2)"""
    finished_at = _aware(task.finished_at) or _aware(task.updated_at) or now
    age = (now - finished_at).total_seconds()
    if task.status == TASK_LOST:
        grace = settings.scheduler.lost_outcome_grace_seconds
        drain = settings.logs.log_drain_timeout_seconds
        reclaimed = True
        for e in executions:
            if e.status == states.EXEC_LOST and not await outbox_svc.reclaim_ever_issued(
                session, e.id
            ):
                reclaimed = False
                break
        if not (reclaimed and age >= drain):
            if grace <= 0 or age < grace:
                return False
    drain_fallback = settings.logs.log_drain_timeout_seconds + FALLBACK_GRACE_SECONDS
    still_open = any(lf.status in (LOG_ACTIVE, LOG_FINALIZING) for lf in log_files)
    if still_open and age < drain_fallback:
        return False
    return True


def _seal(log_files: list[ExecutionLogFile], now: datetime) -> None:
    for lf in log_files:
        if lf.status in (LOG_ACTIVE, LOG_FINALIZING):
            lf.status = LOG_COMPLETE
            lf.final_offset = lf.size_bytes
            if lf.finished_at is None:
                lf.finished_at = now


def _count_consecutive(rows: list[ScheduleOutcomeLedger]) -> int:
    n = 0
    for row in rows:
        if not row.erroneous:
            break
        n += 1
    return n


async def _record_ledger(
    session: AsyncSession,
    settings: Settings,
    task: Task,
    erroneous: bool,
    now: datetime,
) -> str | None:
    """Upsert the ledger row, recompute the run, auto-disable at threshold.

    Returns the schedule id when it was just disabled, else None.
    """
    schedule = (
        await session.execute(
            select(Schedule)
            .where(Schedule.id == task.schedule_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if schedule is None:
        return None
    generation = int(task.schedule_generation if task.schedule_generation is not None else 0)
    finished_at = _aware(task.finished_at) or now
    row = (
        await session.execute(
            select(ScheduleOutcomeLedger).where(ScheduleOutcomeLedger.task_id == task.id)
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            ScheduleOutcomeLedger(
                schedule_id=schedule.id, task_id=task.id, generation=generation,
                finished_at=finished_at, erroneous=erroneous, recorded_at=now,
            )
        )
    else:
        row.erroneous = erroneous
        row.finished_at = finished_at
        row.generation = generation
        row.recorded_at = now
    await session.flush()

    # Self-trim: keep the newest max(100, 2 * threshold) rows per schedule.
    threshold = int(settings.scheduler.auto_disable_after_errors)
    keep = max(LEDGER_MIN_KEEP, 2 * max(0, threshold))
    ids = (
        await session.execute(
            select(ScheduleOutcomeLedger.id)
            .where(ScheduleOutcomeLedger.schedule_id == schedule.id)
            .order_by(
                ScheduleOutcomeLedger.finished_at.desc(), ScheduleOutcomeLedger.id.desc()
            )
            .offset(keep)
        )
    ).scalars().all()
    if ids:
        await session.execute(
            delete(ScheduleOutcomeLedger).where(ScheduleOutcomeLedger.id.in_(list(ids)))
        )

    # Recompute the run from the ledger (current generation, newest first).
    current = int(schedule.outcome_generation or 0)
    rows = list(
        (
            await session.execute(
                select(ScheduleOutcomeLedger)
                .where(
                    ScheduleOutcomeLedger.schedule_id == schedule.id,
                    ScheduleOutcomeLedger.generation == current,
                )
                .order_by(
                    ScheduleOutcomeLedger.finished_at.desc(), ScheduleOutcomeLedger.id.desc()
                )
            )
        ).scalars().all()
    )
    consecutive = _count_consecutive(rows)
    schedule.consecutive_error_count = consecutive
    if threshold > 0 and consecutive >= threshold and schedule.enabled:
        task_ids = [r.task_id for r in rows[:consecutive]]
        schedule.enabled = False
        schedule.auto_disabled_at = now
        schedule.auto_disabled_reason = {
            "consecutive_errors": consecutive,
            "threshold": threshold,
            "task_ids": task_ids[:threshold],
            "last_error": {
                "task_id": task.id,
                "status": task.status,
                "finished_at": finished_at.isoformat(),
            },
        }
        try:
            await notif.notify(
                session,
                type=TYPE_SCHEDULE_AUTO_DISABLED,
                severity=SEVERITY_ERROR,
                payload={
                    "schedule_id": schedule.id,
                    "schedule_name": schedule.name,
                    "consecutive_errors": consecutive,
                    "threshold": threshold,
                    "task_ids": task_ids[:threshold],
                },
                dedupe_key=schedule.id,
            )
        except Exception:  # noqa: BLE001 - alerting never breaks recording
            logger.warning("schedule_auto_disabled notify failed", exc_info=True)
        logger.warning(
            "schedule %s (%s) auto-disabled after %d consecutive erroneous runs",
            schedule.id, schedule.name, consecutive,
        )
        return schedule.id
    return None


async def record_task_outcomes(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> list[str]:
    """Record every ready terminal task; returns schedule ids disabled. Caller commits."""
    now = now or datetime.now(UTC)
    disabled: list[str] = []
    for task_id in await _candidates(session, limit):
        task, executions, by_exec, log_files = await _lock_task_graph(session, task_id)
        if task is None:
            continue
        # Re-read under the lock: the status may have moved (e.g. lost -> complete)
        # or the stamp may have been set by a concurrent tick.
        if task.status not in TASK_TERMINAL or task.outcome_recorded_at is not None:
            continue
        if not await _ready(session, settings, task, executions, log_files, now):
            continue
        _seal(log_files, now)
        erroneous = states.task_is_erroneous(
            task, executions, by_exec, settings.logs.max_file_bytes
        )
        task.outcome_erroneous = erroneous
        task.outcome_recorded_at = now
        if task.schedule_id and task.source in COUNTED_SOURCES:
            sid = await _record_ledger(session, settings, task, erroneous, now)
            if sid is not None:
                disabled.append(sid)
        await session.flush()
    return disabled

