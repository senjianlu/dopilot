"""Schedule service (phase 1.7 packet 2): CRUD + trigger-now + timer firing.

A :class:`Schedule` references one :class:`TaskTemplate` and creates tasks from
its snapshot. Two firing paths, both routed through
:func:`dispatch.dispatch_from_template` so they share the manual run code path:

- :func:`trigger_now` — the immediate ``POST /schedules/{id}/trigger-now``
  endpoint (``source=schedule_trigger_now``). NEVER coalesced (user decision #2).
- :func:`fire_timer` — what the APScheduler runner calls on each tick
  (``source=schedule_timer``). Subject to the schedule-keyed coalesce: it is
  suppressed only when the schedule already has an UNDISPATCHED backlog task
  (Redis-outage backlog), never because a prior run is merely running.

Pause/resume is out of scope; there is no paused state.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..models.scheduling import Schedule
from ..redis.dispatcher import CommandDispatcher
from . import states, templates
from .dispatch import dispatch_from_template
from .executions import _iso, new_id
from .outbox import has_undispatched_backlog_for_schedule

VALID_TRIGGER_TYPES = frozenset({"interval", "cron"})


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


async def create_schedule(
    session: AsyncSession, data: dict[str, Any]
) -> Schedule:
    if not (data.get("name") or "").strip():
        raise ApiError(
            400, "schedule.invalid_params", "errors.invalidParams",
            {"missing": ["name"]},
        )
    # template must exist (FK + a friendly 404-equivalent at create).
    await templates.get_template_or_404(session, data.get("template_id") or "")
    _validate_trigger(data)
    trigger_type = data.get("trigger_type") or "interval"
    schedule = Schedule(
        id=new_id(),
        name=str(data["name"]).strip(),
        description=data.get("description"),
        template_id=str(data["template_id"]),
        trigger_type=trigger_type,
        interval_seconds=(
            int(data["interval_seconds"]) if trigger_type == "interval" else None
        ),
        cron=(str(data["cron"]).strip() if trigger_type == "cron" else None),
    )
    session.add(schedule)
    return schedule


async def update_schedule(
    session: AsyncSession, schedule: Schedule, data: dict[str, Any]
) -> Schedule:
    if "template_id" in data:
        await templates.get_template_or_404(session, data["template_id"])
        schedule.template_id = str(data["template_id"])
    if "name" in data and (data.get("name") or "").strip():
        schedule.name = str(data["name"]).strip()
    if "description" in data:
        schedule.description = data["description"]
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
    result = await session.execute(
        select(Schedule).order_by(Schedule.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def delete_schedule(session: AsyncSession, schedule: Schedule) -> None:
    await session.delete(schedule)


async def trigger_now(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    schedule: Schedule,
):
    """Immediate trigger: create+dispatch a task from the template snapshot.

    NEVER coalesced — an explicit user trigger always produces a new task, even
    while an earlier task from the same schedule is still active.
    """
    template = await templates.get_template_or_404(
        session, schedule.template_id
    )
    return await dispatch_from_template(
        session,
        settings,
        dispatcher,
        template,
        source=states.TASK_SOURCE_TRIGGER_NOW,
        schedule_id=schedule.id,
    )


async def fire_timer(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    schedule: Schedule,
):
    """Timer firing: create+dispatch a task UNLESS undispatched backlog exists.

    Returns the run response, or ``None`` when the firing was coalesced away
    because the schedule still has an undispatched backlog task (Redis outage).
    """
    if await has_undispatched_backlog_for_schedule(session, schedule.id):
        return None
    template = await templates.get_template_or_404(
        session, schedule.template_id
    )
    return await dispatch_from_template(
        session,
        settings,
        dispatcher,
        template,
        source=states.TASK_SOURCE_TIMER,
        schedule_id=schedule.id,
    )


def schedule_view(schedule: Schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "template_id": schedule.template_id,
        "trigger_type": schedule.trigger_type,
        "interval_seconds": schedule.interval_seconds,
        "cron": schedule.cron,
        "created_at": _iso(schedule.created_at),
        "updated_at": _iso(schedule.updated_at),
    }
