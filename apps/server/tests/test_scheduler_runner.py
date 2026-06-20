"""ScheduleRunner tests (phase 1.7 final acceptance).

Both packet codex reviews flagged the same residual risk: the live APScheduler
wiring in ``scheduler/runner.py`` (trigger construction, ``start``, ``reload``,
and the ``_fire`` timer callback) had no running-timer coverage — only
``fire_timer`` was unit-tested directly. These tests close that gap WITHOUT
waiting on real wall-clock minutes: they start a real ``AsyncIOScheduler``,
assert it registers/reloads one job per schedule, and invoke the timer callback
path (``_fire``) directly to prove a firing creates a ``schedule_timer`` task
and lands one run command on the agent's Redis command stream — the same
dispatch path as a manual run.
"""

from __future__ import annotations

import dataclasses

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dopilot_protocol import AgentCommand, command_stream, from_stream_entry
from dopilot_server.config.settings import RedisSettings
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.scheduler.runner import (
    ScheduleRunner,
    build_schedule_runner,
)
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services import states, templates
from dopilot_server.services.executions import list_tasks


def _dispatcher(sessionmaker, redis) -> CommandDispatcher:
    return CommandDispatcher(sessionmaker, CommandProducer(redis, RedisSettings()))


async def _run_commands(redis, agent_id="agent-1") -> list[AgentCommand]:
    entries = await redis.entries(command_stream(agent_id))
    return [from_stream_entry(AgentCommand, f) for _id, f in entries]


async def _seed_build_artifact(session):
    import uuid

    from dopilot_server.models.execution import BuildArtifact

    sha = uuid.uuid4().hex * 2  # 64 chars
    artifact = BuildArtifact(
        id=uuid.uuid4().hex,
        artifact_type="scrapy",
        package_format="egg",
        name="demo",
        filename="demo.egg",
        content_hash=sha,
        size_bytes=1,
        artifact_metadata={
            "project": "demo",
            "version": f"sha256-{sha[:12]}",
            "spiders": ["phase1"],
            "fetch_path": f"/api/v1/artifacts/scrapy/{sha}/egg",
        },
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def _seed_schedule(session, **overrides):
    """Commit a template + schedule and return ``(template, schedule)``."""
    artifact = await _seed_build_artifact(session)
    template = await templates.create_template(
        session,
        {
            "name": "runner-template",
            "build_artifact_id": artifact.id,
            "spider": "phase1",
            "node_strategy": "all",
        },
    )
    await session.flush()
    schedule = await sched_svc.create_schedule(
        session,
        {
            "name": "every-30s",
            "execution_template_id": template.id,
            "interval_seconds": 30,
            **overrides,
        },
    )
    await session.commit()
    return template, schedule


# ---------------------------------------------------------------------------
# build_schedule_runner gating
# ---------------------------------------------------------------------------


def test_build_runner_disabled_returns_none(
    exec_settings, test_sessionmaker, exec_redis
):
    assert exec_settings.scheduler.enabled is False
    runner = build_schedule_runner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )
    assert runner is None


def test_build_runner_enabled_returns_runner(
    exec_settings, test_sessionmaker, exec_redis
):
    # SchedulerSettings is mutable; flip `enabled` on a deep copy of settings.
    enabled = exec_settings.model_copy(deep=True)
    enabled.scheduler.enabled = True
    runner = build_schedule_runner(
        test_sessionmaker, enabled, _dispatcher(test_sessionmaker, exec_redis)
    )
    assert isinstance(runner, ScheduleRunner)


# ---------------------------------------------------------------------------
# trigger construction
# ---------------------------------------------------------------------------


def test_build_trigger_interval_and_cron(
    exec_settings, test_sessionmaker, exec_redis
):
    runner = ScheduleRunner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )

    @dataclasses.dataclass
    class _S:
        trigger_type: str
        interval_seconds: int | None
        cron: str | None

    interval_trigger = runner._build_trigger(_S("interval", 45, None))
    assert isinstance(interval_trigger, IntervalTrigger)
    assert interval_trigger.interval.total_seconds() == 45

    cron_trigger = runner._build_trigger(_S("cron", None, "*/5 * * * *"))
    assert isinstance(cron_trigger, CronTrigger)


# ---------------------------------------------------------------------------
# start / reload register one job per schedule
# ---------------------------------------------------------------------------


async def test_runner_registers_job_on_start(
    db_session, exec_settings, test_sessionmaker, exec_redis
):
    _, schedule = await _seed_schedule(db_session)
    runner = ScheduleRunner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )
    await runner.start()
    try:
        jobs = runner._scheduler.get_jobs()
        assert [j.id for j in jobs] == [schedule.id]
    finally:
        await runner.stop()
    assert runner._scheduler is None


async def test_runner_reload_syncs_added_and_removed_jobs(
    db_session, exec_settings, test_sessionmaker, exec_redis
):
    template, first = await _seed_schedule(db_session)
    runner = ScheduleRunner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )
    await runner.start()
    try:
        assert {j.id for j in runner._scheduler.get_jobs()} == {first.id}

        # Add a second schedule for the same template, then reload.
        second = await sched_svc.create_schedule(
            db_session,
            {
                "name": "s2",
                "execution_template_id": template.id,
                "interval_seconds": 60,
            },
        )
        await db_session.commit()
        await runner.reload()
        assert {j.id for j in runner._scheduler.get_jobs()} == {
            first.id,
            second.id,
        }

        # Delete the first schedule, then reload: its job is removed.
        await sched_svc.delete_schedule(db_session, first)
        await db_session.commit()
        await runner.reload()
        assert {j.id for j in runner._scheduler.get_jobs()} == {second.id}
    finally:
        await runner.stop()


async def test_reload_before_start_is_noop(
    exec_settings, test_sessionmaker, exec_redis
):
    runner = ScheduleRunner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )
    # No scheduler yet (start() not called); reload must not raise.
    await runner.reload()
    assert runner._scheduler is None


# ---------------------------------------------------------------------------
# the timer callback path (_fire) creates a real schedule_timer task
# ---------------------------------------------------------------------------


async def test_fire_creates_timer_task_with_one_run_command(
    db_session, exec_settings, seeder, test_sessionmaker, exec_redis
):
    await seeder.healthy_node()
    _, schedule = await _seed_schedule(db_session)

    runner = ScheduleRunner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )
    # Drive the timer callback directly — what AsyncIOScheduler invokes on a
    # tick — instead of waiting on a real interval.
    await runner._fire(schedule.id)

    tasks = await list_tasks(db_session)
    timer_tasks = [t for t in tasks if t.schedule_id == schedule.id]
    assert len(timer_tasks) == 1
    task = timer_tasks[0]
    assert task.source == states.TASK_SOURCE_TIMER
    assert task.status == states.TASK_QUEUED
    # One healthy node + strategy=all -> exactly one run command on the wire.
    cmds = await _run_commands(exec_redis)
    assert len(cmds) == 1
    assert cmds[0].type.value == "run"
    # Wire seam: the run command carries execution_id == the TASK id.
    assert cmds[0].execution_id == task.id


async def test_fire_unknown_schedule_is_noop(
    db_session, exec_settings, test_sessionmaker, exec_redis
):
    runner = ScheduleRunner(
        test_sessionmaker,
        exec_settings,
        _dispatcher(test_sessionmaker, exec_redis),
    )
    # Missing schedule id: callback returns quietly, no task created.
    await runner._fire("does-not-exist")
    assert await list_tasks(db_session) == []
