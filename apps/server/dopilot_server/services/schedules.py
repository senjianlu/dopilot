"""Schedule service (phase 1.8): CRUD + trigger-now + timer firing.

A :class:`Schedule` references one :class:`ExecutionTemplate` and creates tasks
from its resolved snapshot (schedule ``overrides`` applied with precedence:
override > template default > build artifact default). Two firing paths, both
routed through :func:`dispatch.run_execution_template` so they share one path:

- :func:`trigger_now` — the immediate ``POST /schedules/{id}/trigger-now``
  endpoint (``source=schedule_trigger_now``). NEVER coalesced (user decision #2).
- :func:`fire_timer` — what the APScheduler runner calls on each tick
  (``source=schedule_timer``). Subject to the schedule-keyed coalesce: it is
  suppressed only when the schedule already has an UNDISPATCHED backlog task
  (Redis-outage backlog), never because a prior run is merely running. Phase
  2.2: it also defensively no-ops for a disabled schedule.

Phase 2.2: schedules carry a row-level ``enabled`` flag (default false). Only
enabled schedules are registered with APScheduler and fire on a timer; disabled
schedules stay listable/editable/deletable and remain manually runnable via
:func:`trigger_now`. This is the "pause/resume" of timer firing (distinct from
the global ``[scheduler].enabled``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..models.execution import Task
from ..models.scheduling import Schedule
from ..redis.dispatcher import CommandDispatcher
from . import resolve, states, templates
from .dispatch import run_execution_template
from .executions import _iso, new_id
from .outbox import has_undispatched_backlog_for_schedule

logger = logging.getLogger(__name__)

VALID_TRIGGER_TYPES = frozenset({"interval", "cron"})

# Concurrency gate (decision 0022) --------------------------------------------
# ``max_concurrency`` lives in a signed 32-bit Integer column; validating the
# upper bound here turns "2147483648" into a structured 400 instead of a
# DataError/500 at COMMIT time.
MAX_CONCURRENCY_CEILING = 2147483647

# Why a firing was NOT admitted. Four distinct reasons: the caller needs to tell
# them apart (only the concurrency one may be logged as "over the limit", and
# only it carries active/limit counts).
SKIP_MISSING = "missing"
SKIP_DISABLED = "disabled"
SKIP_BACKLOG = "backlog"
SKIP_CONCURRENCY = "concurrency"


@dataclass(frozen=True)
class FiringSlot:
    """Admission decision for one schedule firing.

    ``granted`` true means ``schedule`` is the row AS READ UNDER THE LOCK — the
    caller must use that instance (its ``overrides`` / ``outcome_generation``
    are the authoritative values, a pre-lock copy may be stale).
    """

    granted: bool
    schedule: Schedule | None = None
    skip_reason: str | None = None
    active: int | None = None
    limit: int | None = None


def _validate_trigger(data: dict[str, Any]) -> None:
    trigger_type = data.get("trigger_type") or "interval"
    if trigger_type not in VALID_TRIGGER_TYPES:
        raise ApiError(
            400,
            "schedule.invalid_trigger_type",
            "errors.invalidTriggerType",
            {"trigger_type": trigger_type},
        )
    if trigger_type == "interval":
        interval = data.get("interval_seconds")
        if not isinstance(interval, int) or interval <= 0:
            raise ApiError(
                400,
                "schedule.invalid_interval",
                "errors.invalidInterval",
                {"interval_seconds": interval},
            )
    else:  # cron
        cron = (data.get("cron") or "").strip()
        # APScheduler CronTrigger.from_crontab needs 5 whitespace fields and
        # validates value ranges. Validate here so create/update returns a
        # structured 400 instead of committing and then failing during runner
        # reload.
        try:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(cron)
        except Exception:
            raise ApiError(
                400,
                "schedule.invalid_cron",
                "errors.invalidCron",
                {"cron": data.get("cron")},
            ) from None


def _validate_max_concurrency(value: Any) -> int:
    """Return ``value`` as a valid concurrency limit, or raise a 400.

    Rejects bools explicitly. ``isinstance(True, int)`` is True, and Pydantic's
    lax mode already coerces JSON ``false`` to ``0`` — which is precisely the
    "unlimited" sentinel. A mistyped ``false`` must never silently switch the
    whole gate off, so both this layer and the request schema refuse bools.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(
            400,
            "schedule.invalid_max_concurrency",
            "errors.invalidMaxConcurrency",
            {"max_concurrency": value},
        )
    if value < 0 or value > MAX_CONCURRENCY_CEILING:
        raise ApiError(
            400,
            "schedule.invalid_max_concurrency",
            "errors.invalidMaxConcurrency",
            {"max_concurrency": value, "max": MAX_CONCURRENCY_CEILING},
        )
    return value


async def _ensure_unique_name(
    session: AsyncSession, name: str, *, exclude_id: str | None = None
) -> None:
    """Raise 409 if another schedule already uses ``name`` (phase 2.2).

    Checked in service code before commit so the API returns a deterministic
    ``schedule.name_conflict`` instead of a raw DB IntegrityError. ``exclude_id``
    excludes the row being updated (rename self-exclusion).
    """
    stmt = select(Schedule.id).where(Schedule.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Schedule.id != exclude_id)
    if (await session.execute(stmt.limit(1))).first() is not None:
        raise ApiError(
            409,
            "schedule.name_conflict",
            "errors.scheduleNameConflict",
            {"name": name},
        )


async def create_schedule(
    session: AsyncSession, data: dict[str, Any]
) -> Schedule:
    if not (data.get("name") or "").strip():
        raise ApiError(
            400, "schedule.invalid_params", "errors.invalidParams",
            {"missing": ["name"]},
        )
    await _ensure_unique_name(session, str(data["name"]).strip())
    # execution template must exist (FK + a friendly 404-equivalent at create).
    template = await templates.get_template_or_404(
        session, data.get("execution_template_id") or ""
    )
    # Type-aware override validation: a wheel template's command override is a
    # free-form shell command, not a ``scrapy crawl`` command (phase 2b).
    artifact_type = await templates.artifact_type_for_template(session, template)
    _validate_trigger(data)
    trigger_type = data.get("trigger_type") or "interval"
    max_concurrency = _validate_max_concurrency(
        data["max_concurrency"] if "max_concurrency" in data else 1
    )
    schedule = Schedule(
        id=new_id(),
        name=str(data["name"]).strip(),
        description=data.get("description"),
        max_concurrency=max_concurrency,
        # Phase 2.2: default disabled when omitted; only an explicit true enables
        # timer firing. trigger-now works regardless.
        enabled=bool(data.get("enabled", False)),
        execution_template_id=str(data["execution_template_id"]),
        trigger_type=trigger_type,
        interval_seconds=(
            int(data["interval_seconds"]) if trigger_type == "interval" else None
        ),
        cron=(str(data["cron"]).strip() if trigger_type == "cron" else None),
        overrides=resolve.sanitize_overrides(
            data.get("overrides"), artifact_type=artifact_type
        ),
    )
    session.add(schedule)
    return schedule


async def update_schedule(
    session: AsyncSession, schedule: Schedule, data: dict[str, Any]
) -> Schedule:
    if "execution_template_id" in data:
        await templates.get_template_or_404(
            session, data["execution_template_id"]
        )
        schedule.execution_template_id = str(data["execution_template_id"])
    if "name" in data and (data.get("name") or "").strip():
        new_name = str(data["name"]).strip()
        await _ensure_unique_name(session, new_name, exclude_id=schedule.id)
        schedule.name = new_name
    if "description" in data:
        schedule.description = data["description"]
    if "max_concurrency" in data:
        schedule.max_concurrency = _validate_max_concurrency(
            data["max_concurrency"]
        )
    if "enabled" in data:
        enabling = bool(data["enabled"]) and not schedule.enabled
        schedule.enabled = bool(data["enabled"])
        if enabling:
            # Log-flood guard / auto-disable: a manual re-enable starts a new
            # outcome generation — the derived counter restarts at 0 and tasks
            # created before this instant (even when their terminal arrives
            # later) never count toward the new run.
            schedule.outcome_generation = int(schedule.outcome_generation or 0) + 1
            schedule.consecutive_error_count = 0
            schedule.auto_disabled_at = None
            schedule.auto_disabled_reason = None
    if "overrides" in data:
        template = await templates.get_template_or_404(
            session, schedule.execution_template_id
        )
        artifact_type = await templates.artifact_type_for_template(
            session, template
        )
        schedule.overrides = resolve.sanitize_overrides(
            data.get("overrides"), artifact_type=artifact_type
        )
    # Re-validate the trigger as a whole when any trigger field changes.
    if {"trigger_type", "interval_seconds", "cron"} & set(data):
        merged = {
            "trigger_type": data.get("trigger_type", schedule.trigger_type),
            "interval_seconds": data.get(
                "interval_seconds", schedule.interval_seconds
            ),
            "cron": data.get("cron", schedule.cron),
        }
        _validate_trigger(merged)
        schedule.trigger_type = merged["trigger_type"]
        if schedule.trigger_type == "interval":
            schedule.interval_seconds = int(merged["interval_seconds"])
            schedule.cron = None
        else:
            schedule.cron = str(merged["cron"]).strip()
            schedule.interval_seconds = None
    return schedule


async def get_schedule(
    session: AsyncSession, schedule_id: str
) -> Schedule | None:
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    return result.scalar_one_or_none()


async def get_schedule_or_404(
    session: AsyncSession, schedule_id: str
) -> Schedule:
    schedule = await get_schedule(session, schedule_id)
    if schedule is None:
        raise ApiError(
            404,
            "schedule.not_found",
            "errors.scheduleNotFound",
            {"schedule_id": schedule_id},
        )
    return schedule


async def list_schedules(
    session: AsyncSession, limit: int = 200
) -> list[Schedule]:
    """All schedules (enabled and disabled). The shared API list path uses this
    so disabled rows stay visible to users and to later reconcile work."""
    result = await session.execute(
        select(Schedule).order_by(Schedule.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def list_enabled_schedules(
    session: AsyncSession, limit: int = 200
) -> list[Schedule]:
    """Only enabled schedules — what :class:`ScheduleRunner` registers (phase
    2.2). Disabled schedules are never given an APScheduler job."""
    result = await session.execute(
        select(Schedule)
        .where(Schedule.enabled.is_(True))
        .order_by(Schedule.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def disable_all_schedules(session: AsyncSession) -> int:
    """Bulk-disable every enabled schedule; returns the number disabled.

    One-shot pre-upgrade brake: a single UPDATE (atomic, unlike a per-row PUT
    loop) so a partial failure can never leave half the schedules firing. The
    column-level ``onupdate`` refreshes ``updated_at`` on the touched rows.
    """
    result = await session.execute(
        update(Schedule).where(Schedule.enabled.is_(True)).values(enabled=False)
    )
    return int(result.rowcount or 0)


async def count_enabled_schedules(session: AsyncSession) -> int:
    """Global enabled count, deliberately NOT bounded by the list limit.

    Backs the Web "disable all" button state + confirm copy: the list endpoint
    truncates at 200 rows, so inferring "nothing enabled" from the loaded page
    would wrongly disable the button when only older rows are enabled.
    """
    result = await session.execute(
        select(func.count())
        .select_from(Schedule)
        .where(Schedule.enabled.is_(True))
    )
    return int(result.scalar_one())


async def delete_schedule(session: AsyncSession, schedule: Schedule) -> None:
    await session.delete(schedule)


async def count_active_tasks_for_schedule(
    session: AsyncSession, schedule_id: str
) -> int:
    """Count this schedule's ACTIVE tasks (the concurrency gate's numerator).

    ``states.TASK_ACTIVE`` (queued/running/finalizing) is referenced directly so
    the set can never drift from the state machine. Counted per TASK, not per
    execution: one task that fans out to N nodes still occupies ONE slot. No
    ``source`` filter — timer firings and manual trigger-now deliberately share
    one quota (that is what "manual triggers count too" means).
    """
    result = await session.execute(
        select(func.count())
        .select_from(Task)
        .where(
            Task.schedule_id == schedule_id,
            Task.status.in_(states.TASK_ACTIVE),
        )
    )
    return int(result.scalar_one())


async def acquire_firing_slot(
    session: AsyncSession,
    schedule_id: str,
    *,
    raise_on_full: bool,
    require_enabled: bool,
    coalesce_backlog: bool,
) -> FiringSlot:
    """The single admission gate for one schedule firing (decision 0022).

    Everything is decided INSIDE one ``FOR UPDATE`` serialized region: exists ->
    enabled -> backlog coalesce -> concurrency. Two reasons it must be this way:

    - the caller's ``Schedule`` may predate the lock, and ``max_concurrency``
      can be changed by a concurrent PUT; deciding on a pre-lock value (the
      ``== 0`` fast path included) lets a firing slip past a limit that was
      already tightened and committed. ``populate_existing=True`` overwrites the
      stale identity-map copy with the row as it is under the lock;
    - the backlog query only sees COMMITTED rows. Run before the lock, a timer
      would read "no backlog", then block on the lock while trigger-now commits
      a task with an unresolved outbox, then create a second one anyway.

    The lock is released by the executor's atomic create commit, which happens
    BEFORE the XADD (``executors/scrapyd.py``), so it never spans Redis I/O.
    Only this one row is locked and no task/execution lock is taken while
    holding it, so it cannot form a cycle with the
    ``task -> executions -> log files -> schedule`` order used by terminal
    writers.
    """
    stmt = (
        select(Schedule)
        .where(Schedule.id == schedule_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    schedule = (await session.execute(stmt)).scalar_one_or_none()
    if schedule is None:
        if raise_on_full:
            raise ApiError(
                404,
                "schedule.not_found",
                "errors.scheduleNotFound",
                {"schedule_id": schedule_id},
            )
        return FiringSlot(granted=False, skip_reason=SKIP_MISSING)

    if require_enabled and not schedule.enabled:
        return FiringSlot(granted=False, skip_reason=SKIP_DISABLED)

    if coalesce_backlog and await has_undispatched_backlog_for_schedule(
        session, schedule_id
    ):
        return FiringSlot(granted=False, skip_reason=SKIP_BACKLOG)

    limit = int(schedule.max_concurrency or 0)
    if limit == 0:  # 0 = unlimited (pre-0022 behaviour, kept as escape hatch)
        return FiringSlot(granted=True, schedule=schedule)

    active = await count_active_tasks_for_schedule(session, schedule_id)
    if active >= limit:
        if raise_on_full:
            raise ApiError(
                409,
                "schedule.concurrency_limit",
                "errors.scheduleConcurrencyLimit",
                {"active": active, "limit": limit},
            )
        return FiringSlot(
            granted=False,
            skip_reason=SKIP_CONCURRENCY,
            active=active,
            limit=limit,
        )
    return FiringSlot(granted=True, schedule=schedule)


async def trigger_now(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    schedule: Schedule,
):
    """Immediate trigger: create+dispatch a task from the template snapshot.

    NEVER coalesced — an explicit user trigger always produces a new task even
    while an earlier one is still active. It IS however subject to the
    concurrency gate (decision 0022): manual triggers draw on the same quota as
    timer firings, so an over-limit trigger raises 409 and creates nothing.
    Still allowed for a DISABLED schedule (disabled only pauses the timer).
    """
    slot = await acquire_firing_slot(
        session,
        schedule.id,
        raise_on_full=True,
        require_enabled=False,
        coalesce_backlog=False,
    )
    locked = slot.schedule or schedule
    template = await templates.get_template_or_404(
        session, locked.execution_template_id
    )
    return await run_execution_template(
        session,
        settings,
        dispatcher,
        template,
        source=states.TASK_SOURCE_TRIGGER_NOW,
        schedule_id=locked.id,
        overrides=locked.overrides,
        schedule_generation=int(locked.outcome_generation or 0),
    )


async def fire_timer(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    schedule: Schedule,
):
    """Timer firing: create+dispatch a task unless the admission gate says no.

    Returns the run response, or ``None`` when the firing was skipped. All three
    historical skip conditions (schedule disabled, undispatched backlog) plus the
    new concurrency limit are decided inside ``acquire_firing_slot``'s locked
    region — same outcomes as before, now serializable against a concurrent
    trigger-now.

    Only an over-the-limit skip is logged: reporting a disabled schedule or a
    routine backlog coalesce as "concurrency" would make the log lie. Skips are
    otherwise silent by design — no notification, and ``consecutive_error_count``
    is untouched (a skipped run is not a failed run, so it must never feed
    auto-disable).
    """
    slot = await acquire_firing_slot(
        session,
        schedule.id,
        raise_on_full=False,
        require_enabled=True,
        coalesce_backlog=True,
    )
    if not slot.granted:
        if slot.skip_reason == SKIP_CONCURRENCY:
            logger.info(
                "schedule %s timer firing skipped: concurrency %d/%d",
                schedule.id,
                slot.active,
                slot.limit,
            )
        return None
    locked = slot.schedule or schedule
    template = await templates.get_template_or_404(
        session, locked.execution_template_id
    )
    return await run_execution_template(
        session,
        settings,
        dispatcher,
        template,
        source=states.TASK_SOURCE_TIMER,
        schedule_id=locked.id,
        overrides=locked.overrides,
        schedule_generation=int(locked.outcome_generation or 0),
    )


def compute_next_run_at(
    *,
    trigger_type: str,
    interval_seconds: int | None,
    cron: str | None,
    timezone: str = "UTC",
    now: datetime | None = None,
) -> datetime | None:
    """Estimate the next fire time from a trigger definition + ``now``.

    Phase 1.7.1: interval next-run is an ESTIMATE (``now + interval_seconds``) —
    the persisted scheduler's exact next fire is only known to a live APScheduler
    job. Cron is computed deterministically via APScheduler's ``CronTrigger``.
    Returns ``None`` when the trigger is unusable (no interval / bad cron).
    """
    now = now or datetime.now(UTC)
    if trigger_type == "cron" and cron:
        try:
            from apscheduler.triggers.cron import CronTrigger

            trig = CronTrigger.from_crontab(cron, timezone=timezone)
            aware_now = now if now.tzinfo else now.replace(tzinfo=UTC)
            return trig.get_next_fire_time(None, aware_now)
        except Exception:  # noqa: BLE001 - bad cron -> no estimate
            return None
    if trigger_type == "interval" and interval_seconds and interval_seconds > 0:
        base = now if now.tzinfo else now.replace(tzinfo=UTC)
        return base + timedelta(seconds=interval_seconds)
    return None


def preview_next_run(
    data: dict[str, Any], *, timezone: str = "UTC", now: datetime | None = None
) -> datetime | None:
    """Validate a trigger payload and compute its estimated next run."""
    _validate_trigger(data)
    return compute_next_run_at(
        trigger_type=data.get("trigger_type") or "interval",
        interval_seconds=data.get("interval_seconds"),
        cron=data.get("cron"),
        timezone=timezone,
        now=now,
    )


def schedule_view(
    schedule: Schedule, *, timezone: str = "UTC", now: datetime | None = None
) -> dict[str, Any]:
    next_run = compute_next_run_at(
        trigger_type=schedule.trigger_type,
        interval_seconds=schedule.interval_seconds,
        cron=schedule.cron,
        timezone=timezone,
        now=now,
    )
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "enabled": schedule.enabled,
        "max_concurrency": int(schedule.max_concurrency or 0),
        "execution_template_id": schedule.execution_template_id,
        "trigger_type": schedule.trigger_type,
        "interval_seconds": schedule.interval_seconds,
        "cron": schedule.cron,
        "overrides": dict(schedule.overrides or {}),
        "next_run_at": _iso(next_run),
        "consecutive_error_count": int(schedule.consecutive_error_count or 0),
        "auto_disabled_at": _iso(schedule.auto_disabled_at),
        "auto_disabled_reason": (
            dict(schedule.auto_disabled_reason)
            if schedule.auto_disabled_reason
            else None
        ),
        "outcome_generation": int(schedule.outcome_generation or 0),
        "created_at": _iso(schedule.created_at),
        "updated_at": _iso(schedule.updated_at),
    }
