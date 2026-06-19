"""APScheduler-backed schedule runner (phase 1.7 packet 2).

A SINGLE in-process ``AsyncIOScheduler`` (no distributed lock) drives the
``schedules`` table: each schedule becomes one job whose firing calls
:func:`services.schedules.fire_timer` (``source=schedule_timer``) in a fresh
session. This is why the server is single-replica with ``workers=1`` — multiple
workers would fire every timer multiple times (CLAUDE.md hard constraint).

Trigger engine: interval (``interval_seconds``) or a 5-field crontab (``cron``),
via APScheduler ``>=3.10,<4`` (importlib-based; never 3.6.0). Pause/resume is
out of scope.

The runner is OFF unless ``[scheduler].enabled`` is true; tests exercise
``fire_timer`` / coalesce directly rather than waiting on real timers. The
schedules API calls :meth:`reload` after create/update/delete so the live job
set stays in sync without a restart.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config.settings import Settings
from ..executors.base import DispatchUnknownError
from ..redis.dispatcher import CommandDispatcher
from ..services import schedules as svc


class ScheduleRunner:
    """Owns the AsyncIOScheduler and keeps its jobs in sync with the DB."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        dispatcher: CommandDispatcher,
    ) -> None:
        self._maker = sessionmaker
        self._settings = settings
        self._dispatcher = dispatcher
        self._scheduler = None

    async def start(self) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._scheduler = AsyncIOScheduler(
            timezone=self._settings.scheduler.timezone
        )
        await self.reload()
        self._scheduler.start()

    def _build_trigger(self, schedule):
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        tz = self._settings.scheduler.timezone
        if schedule.trigger_type == "cron" and schedule.cron:
            return CronTrigger.from_crontab(schedule.cron, timezone=tz)
        return IntervalTrigger(
            seconds=schedule.interval_seconds or 60, timezone=tz
        )

    async def reload(self) -> None:
        """Rebuild the job set from the ``schedules`` table."""
        if self._scheduler is None:
            return
        async with self._maker() as session:
            schedules = await svc.list_schedules(session)
        self._scheduler.remove_all_jobs()
        for schedule in schedules:
            self._scheduler.add_job(
                self._fire,
                self._build_trigger(schedule),
                args=[schedule.id],
                id=schedule.id,
                replace_existing=True,
            )

    async def _fire(self, schedule_id: str) -> None:
        async with self._maker() as session:
            schedule = await svc.get_schedule(session, schedule_id)
            if schedule is None:
                return
            try:
                await svc.fire_timer(
                    session, self._settings, self._dispatcher, schedule
                )
            except DispatchUnknownError:
                # XADD landed; the agent's running event converges the task.
                pass

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None


def build_schedule_runner(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    dispatcher: CommandDispatcher,
) -> ScheduleRunner | None:
    """Construct a runner iff ``[scheduler].enabled``; else None (off)."""
    if not settings.scheduler.enabled:
        return None
    return ScheduleRunner(sessionmaker, settings, dispatcher)
