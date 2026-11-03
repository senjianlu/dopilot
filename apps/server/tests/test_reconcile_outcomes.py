"""TC-22: the reconcile loop records outcomes and commits the breaker state;
decision 0025 — the breaker never touches ``enabled``, so the runner's job set
is left alone (no reload)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dopilot_server.config.settings import RedisSettings
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.redis.reconcile import RedisReconcileLoop
from dopilot_server.scheduler.runner import ScheduleRunner
from dopilot_server.services import schedules as sched_svc

from .test_outcomes import _schedule, _task
from .test_scheduler_runner import _seed_schedule


async def test_tick_trips_breaker_without_reloading_runner(
    db_session, exec_settings, seeder, test_sessionmaker, exec_redis, monkeypatch
):
    exec_settings.scheduler.auto_disable_after_errors = 3
    exec_settings.scheduler.enabled = True
    _template, sched = await _seed_schedule(db_session)
    assert sched.enabled is True
    now = datetime.now(UTC)
    for i in range(3):
        await _task(db_session, exec_settings, sched, finished_at=now - timedelta(minutes=10 - i))

    dispatcher = CommandDispatcher(test_sessionmaker, CommandProducer(exec_redis, RedisSettings()))
    runner = ScheduleRunner(test_sessionmaker, exec_settings, dispatcher)
    await runner.start()
    assert [j.id for j in runner._scheduler.get_jobs()] == [sched.id]
    reloads: list[int] = []
    original_reload = runner.reload

    async def counting_reload() -> None:
        reloads.append(1)
        await original_reload()

    monkeypatch.setattr(runner, "reload", counting_reload)

    loop = RedisReconcileLoop(test_sessionmaker, exec_settings)
    await loop._tick()
    # Observed from a FRESH session: the trip is committed by the tick.
    async with test_sessionmaker() as s:
        fresh = await sched_svc.get_schedule(s, sched.id)
        assert fresh.enabled is True and fresh.consecutive_error_count == 3
        assert fresh.breaker_state == "held"
    assert reloads == []  # no reload: the job stays registered, gated at firing time
    assert [j.id for j in runner._scheduler.get_jobs()] == [sched.id]

    # Failed commit -> nothing recorded.
    sched2 = await _schedule(db_session, seeder)  # fresh template + schedule
    for i in range(3):
        await _task(db_session, exec_settings, sched2, finished_at=now - timedelta(minutes=5 - i))

    class Boom(Exception):
        pass

    from sqlalchemy.ext.asyncio import AsyncSession

    async def failing_commit(self):
        raise Boom()

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    loop2 = RedisReconcileLoop(test_sessionmaker, exec_settings)
    try:
        await loop2._tick()
    except Boom:
        pass
    monkeypatch.undo()
    async with test_sessionmaker() as s:
        fresh = await sched_svc.get_schedule(s, sched2.id)
        assert fresh.enabled is True and fresh.consecutive_error_count == 0
        assert fresh.breaker_state == "closed"
    await runner.stop()
