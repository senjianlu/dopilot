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
4. if the task came from a schedule: classify it (``states.task_outcome_class``),
   upsert its row in ``schedule_outcome_ledger`` (by ``task_id``, so a
   corrected soft-lost updates in place), self-trim the ledger, RECOMPUTE the
   schedule's consecutive-error count from the ledger (current generation,
   newest first) and drive the schedule's circuit breaker (decision 0025).

The breaker never touches ``enabled`` (so no APScheduler reload is needed):
``closed`` trips to ``open`` (timed back-off, the timer gate in
``services.schedules`` admits a half-open probe when due) or ``held`` (needs a
human) at the threshold; a current-generation outcome resolves ``half_open``;
any current-generation ``ok`` closes ``open`` / ``held``. Breaker
notifications run inside a SAVEPOINT so a failing notification write can never
abort the transaction that records the outcome.

Returns the ids of schedules whose breaker tripped (closed -> open / held).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import SchedulerSettings, Settings
from ..models.execution import Execution, ExecutionLogFile, Task
from ..models.notification import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    TYPE_SCHEDULE_BREAKER_CLOSED,
    TYPE_SCHEDULE_BREAKER_HELD,
    TYPE_SCHEDULE_BREAKER_OPEN,
)
from ..models.scheduling import ExecutionTemplate, Schedule, ScheduleOutcomeLedger
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

# ---- schedule circuit breaker (decision 0025) ----
BREAKER_CLOSED = "closed"
BREAKER_OPEN = "open"
BREAKER_HALF_OPEN = "half_open"
BREAKER_HELD = "held"
BREAKER_STATES = frozenset({BREAKER_CLOSED, BREAKER_OPEN, BREAKER_HALF_OPEN, BREAKER_HELD})


def breaker_backoff_seconds(sched: SchedulerSettings, level: int) -> int:
    """``min(base * 2**level, max)`` seconds (``level`` >= 0)."""
    base = int(sched.breaker_backoff_base_seconds)
    cap = int(sched.breaker_backoff_max_seconds)
    delay = base
    for _ in range(max(0, int(level))):
        if delay >= cap:
            break
        delay *= 2
    return min(delay, cap)


def breaker_max_level(sched: SchedulerSettings) -> int:
    """The first level whose back-off reaches the cap (levels stop there)."""
    level = 0
    while breaker_backoff_seconds(sched, level) < int(sched.breaker_backoff_max_seconds):
        level += 1
    return level


def clear_breaker(schedule: Schedule) -> None:
    """Put ``schedule`` back to ``closed`` with every breaker field cleared.

    Callers that mean a RESET (manual reset / re-enable) also bump
    ``outcome_generation`` and zero ``consecutive_error_count``; a recovery by a
    successful outcome does not (it stays in the generation it recovered in).
    """
    schedule.breaker_state = BREAKER_CLOSED
    schedule.breaker_level = 0
    schedule.breaker_opened_at = None
    schedule.breaker_retry_at = None
    schedule.breaker_escalated_at = None
    schedule.breaker_reason = None
    schedule.breaker_artifact_id = None


def enter_half_open(schedule: Schedule, sched: SchedulerSettings, now: datetime) -> None:
    """Admit a half-open probe (timer gate, under the schedule row lock).

    Bumps the generation so tasks created before the probe can no longer move
    the breaker; ``breaker_retry_at`` becomes the probe deadline.
    """
    schedule.breaker_state = BREAKER_HALF_OPEN
    schedule.outcome_generation = int(schedule.outcome_generation or 0) + 1
    schedule.consecutive_error_count = 0
    schedule.breaker_retry_at = now + timedelta(seconds=int(sched.breaker_backoff_max_seconds))


async def notify_safely(session: AsyncSession, **kwargs: Any) -> None:
    """Raise a notification inside a SAVEPOINT.

    On PostgreSQL a failed statement aborts the whole transaction, so a bare
    try/except could not save the outcome being recorded; the savepoint keeps a
    failing notification write contained. Alerting never breaks recording.
    """
    try:
        async with session.begin_nested():
            await notif.notify(session, **kwargs)
    except Exception:  # noqa: BLE001 - alerting never breaks recording
        logger.warning("breaker notification %s failed", kwargs.get("type"), exc_info=True)


def _snapshot_artifact_id(task: Task) -> str | None:
    snap = task.template_snapshot if isinstance(task.template_snapshot, dict) else {}
    artifact = snap.get("build_artifact")
    if isinstance(artifact, dict) and isinstance(artifact.get("id"), str):
        return artifact["id"]
    return None


def _row_class(row: ScheduleOutcomeLedger) -> str:
    """A ledger row's class; a pre-0016 erroneous NULL reads as ``broken``."""
    if row.outcome_class:
        return row.outcome_class
    return states.OUTCOME_BROKEN if row.erroneous else states.OUTCOME_OK


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
    outcome_class: str,
    now: datetime,
) -> str | None:
    """Upsert the ledger row, recompute the run, drive the circuit breaker.

    Returns the schedule id when its breaker just tripped (closed -> open /
    held), else None.
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
                finished_at=finished_at, erroneous=erroneous,
                outcome_class=outcome_class, recorded_at=now,
            )
        )
    else:
        row.erroneous = erroneous
        row.outcome_class = outcome_class
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
    return await _drive_breaker(
        session,
        settings.scheduler,
        schedule,
        task=task,
        rows=rows,
        consecutive=consecutive,
        threshold=threshold,
        is_current=generation == current,
        outcome_class=outcome_class,
        finished_at=finished_at,
        now=now,
    )


async def _drive_breaker(
    session: AsyncSession,
    sched: SchedulerSettings,
    schedule: Schedule,
    *,
    task: Task,
    rows: list[ScheduleOutcomeLedger],
    consecutive: int,
    threshold: int,
    is_current: bool,
    outcome_class: str,
    finished_at: datetime,
    now: datetime,
) -> str | None:
    """Apply one recorded outcome to the breaker (decision 0025 state table).

    Runs under the schedule row lock taken by ``_record_ledger``. Old-generation
    outcomes are ledgered but never move the breaker — in ANY state, tripping
    from ``closed`` included (a late old-generation row must not re-trip a
    breaker that a current-generation success just closed).
    """
    if not is_current:
        return None
    state = schedule.breaker_state or BREAKER_CLOSED
    if state == BREAKER_CLOSED:
        if threshold > 0 and consecutive >= threshold and schedule.enabled:
            streak = rows[:consecutive]
            all_broken = all(_row_class(r) == states.OUTCOME_BROKEN for r in streak)
            reason = {
                "kind": states.OUTCOME_BROKEN if all_broken else states.OUTCOME_TRANSIENT,
                "trigger": "threshold",
                "consecutive_errors": consecutive,
                "threshold": threshold,
                "task_ids": [r.task_id for r in streak][:threshold],
                "last_error": {
                    "task_id": task.id,
                    "status": task.status,
                    "outcome_class": outcome_class,
                    "finished_at": finished_at.isoformat(),
                },
            }
            schedule.breaker_opened_at = now
            schedule.breaker_escalated_at = None
            if all_broken:
                await _enter_held(session, schedule, task, reason, consecutive, threshold)
            else:
                schedule.breaker_level = 0
                await _enter_open(session, sched, schedule, reason, consecutive, threshold, now)
            logger.warning(
                "schedule %s (%s) breaker tripped -> %s after %d consecutive erroneous runs",
                schedule.id, schedule.name, schedule.breaker_state, consecutive,
            )
            return schedule.id
        return None
    if outcome_class == states.OUTCOME_OK:
        await _close(session, schedule)
        return None
    if state != BREAKER_HALF_OPEN:
        return None  # open / held: errors and neutral outcomes change nothing
    reason = {
        "kind": outcome_class,
        "trigger": "probe",
        "consecutive_errors": consecutive,
        "threshold": threshold,
        "last_error": {
            "task_id": task.id,
            "status": task.status,
            "outcome_class": outcome_class,
            "finished_at": finished_at.isoformat(),
        },
    }
    if outcome_class == states.OUTCOME_BROKEN:
        await _enter_held(session, schedule, task, reason, consecutive, threshold)
    elif outcome_class == states.OUTCOME_TRANSIENT:
        schedule.breaker_level = min(int(schedule.breaker_level or 0) + 1, breaker_max_level(sched))
        schedule.breaker_state = BREAKER_OPEN
        schedule.breaker_reason = reason
        schedule.breaker_retry_at = now + timedelta(
            seconds=breaker_backoff_seconds(sched, schedule.breaker_level)
        )
        await _maybe_escalate(session, sched, schedule, consecutive, threshold, now)
    else:  # neutral: the probe never really ran (canceled / no node) -> retry it
        schedule.breaker_state = BREAKER_OPEN
        schedule.breaker_retry_at = now
    return None


async def _enter_open(
    session: AsyncSession,
    sched: SchedulerSettings,
    schedule: Schedule,
    reason: dict[str, Any],
    consecutive: int,
    threshold: int,
    now: datetime,
) -> None:
    schedule.breaker_state = BREAKER_OPEN
    schedule.breaker_reason = reason
    schedule.breaker_artifact_id = None
    schedule.breaker_retry_at = now + timedelta(
        seconds=breaker_backoff_seconds(sched, int(schedule.breaker_level or 0))
    )
    await notify_safely(
        session,
        type=TYPE_SCHEDULE_BREAKER_OPEN,
        severity=SEVERITY_WARNING,
        payload={
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "consecutive_errors": consecutive,
            "threshold": threshold,
            "retry_at": schedule.breaker_retry_at.isoformat(),
            "escalated": False,
        },
        dedupe_key=schedule.id,
    )


async def _enter_held(
    session: AsyncSession,
    schedule: Schedule,
    task: Task,
    reason: dict[str, Any],
    consecutive: int,
    threshold: int,
) -> None:
    schedule.breaker_state = BREAKER_HELD
    schedule.breaker_reason = reason
    schedule.breaker_retry_at = None
    # The artifact this verdict was reached on: the timer gate re-probes once
    # the template points at a different one (pull model, no cross-row update).
    schedule.breaker_artifact_id = _snapshot_artifact_id(task)
    await notify_safely(
        session,
        type=TYPE_SCHEDULE_BREAKER_HELD,
        severity=SEVERITY_ERROR,
        payload={
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "consecutive_errors": consecutive,
            "threshold": threshold,
        },
        dedupe_key=schedule.id,
    )


async def _close(session: AsyncSession, schedule: Schedule) -> None:
    opened_at = _aware(schedule.breaker_opened_at)
    clear_breaker(schedule)
    await notify_safely(
        session,
        type=TYPE_SCHEDULE_BREAKER_CLOSED,
        severity=SEVERITY_INFO,
        payload={
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "opened_at": opened_at.isoformat() if opened_at else None,
        },
        dedupe_key=schedule.id,
    )
    logger.info("schedule %s (%s) breaker closed", schedule.id, schedule.name)


async def _maybe_escalate(
    session: AsyncSession,
    sched: SchedulerSettings,
    schedule: Schedule,
    consecutive: int,
    threshold: int,
    now: datetime,
) -> None:
    """Escalate once per episode: open for >= ``breaker_escalate_after_seconds``
    at a failed probe -> the open notification is re-raised as ``error``."""
    after = int(sched.breaker_escalate_after_seconds)
    opened_at = _aware(schedule.breaker_opened_at)
    if after <= 0 or schedule.breaker_escalated_at is not None or opened_at is None:
        return
    if (now - opened_at).total_seconds() < after:
        return
    schedule.breaker_escalated_at = now
    await notify_safely(
        session,
        type=TYPE_SCHEDULE_BREAKER_OPEN,
        severity=SEVERITY_ERROR,
        payload={
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "consecutive_errors": consecutive,
            "threshold": threshold,
            "retry_at": schedule.breaker_retry_at.isoformat()
            if schedule.breaker_retry_at
            else None,
            "escalated": True,
        },
        dedupe_key=schedule.id,
    )


async def current_template_artifact_id(session: AsyncSession, schedule: Schedule) -> str | None:
    """The template's CURRENT committed ``build_artifact_id`` (timer gate)."""
    return (
        await session.execute(
            select(ExecutionTemplate.build_artifact_id).where(
                ExecutionTemplate.id == schedule.execution_template_id
            )
        )
    ).scalar_one_or_none()


async def record_task_outcomes(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> list[str]:
    """Record every ready terminal task; returns ids of schedules whose breaker
    tripped (closed -> open / held). Caller commits."""
    now = now or datetime.now(UTC)
    tripped: list[str] = []
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
            outcome_class = states.task_outcome_class(
                task, executions, by_exec, settings.logs.max_file_bytes
            )
            sid = await _record_ledger(session, settings, task, erroneous, outcome_class, now)
            if sid is not None:
                tripped.append(sid)
        await session.flush()
    return tripped

