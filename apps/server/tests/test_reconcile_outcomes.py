"""TC-22: the reconcile loop records outcomes and reloads the runner AFTER commit."""

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


async def test_tick_reloads_runner_only_after_commit(
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

    calls: list[tuple[str, list[str], bool]] = []

    async def on_disabled(ids: list[str]) -> None:
        # Observed from a FRESH session: the disable must already be committed.
        async with test_sessionmaker() as s:
            fresh = await sched_svc.get_schedule(s, ids[0])
            calls.append(("callback", ids, fresh.enabled))
        await runner.reload()

    loop = RedisReconcileLoop(
        test_sessionmaker, exec_settings, on_schedules_disabled=on_disabled
    )
    await loop._tick()
    assert calls == [("callback", [sched.id], False)]
    assert runner._scheduler.get_jobs() == []  # job set no longer contains the schedule
    async with test_sessionmaker() as s:
        fresh = await sched_svc.get_schedule(s, sched.id)
        assert fresh.enabled is False and fresh.consecutive_error_count == 3

    # Failed commit -> no callback and nothing recorded.
    sched2 = await _schedule(db_session, seeder)  # fresh template + schedule
    for i in range(3):
        await _task(db_session, exec_settings, sched2, finished_at=now - timedelta(minutes=5 - i))
    calls.clear()

    class Boom(Exception):
        pass

    from sqlalchemy.ext.asyncio import AsyncSession

    async def failing_commit(self):
        raise Boom()

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    loop2 = RedisReconcileLoop(
        test_sessionmaker, exec_settings, on_schedules_disabled=on_disabled
    )
    try:
        await loop2._tick()
    except Boom:
        pass
    monkeypatch.undo()
    assert calls == []
    async with test_sessionmaker() as s:
        fresh = await sched_svc.get_schedule(s, sched2.id)
        assert fresh.enabled is True and fresh.consecutive_error_count == 0
    await runner.stop()
