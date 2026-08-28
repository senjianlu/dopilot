"""Schedule concurrency gate under REAL row locks (PostgreSQL only).

SQLite compiles ``FOR UPDATE`` away, so the serialization these tests are about
is unobservable there. Fails (never skips) without ``DOPILOT_TEST_DATABASE_URL``
— see the ``pg_sessionmaker`` fixture.

Everything each test needs (node, artifact, template, schedule, triggering
transactions) is built INSIDE the PostgreSQL session: the shared ``seeder``
fixture is bound to the SQLite ``db_session``, so using it here would seed a
different database and every task would come out ``no_target``.
"""

from __future__ import annotations

import asyncio

from dopilot_protocol import ExecutionRunRequest
from dopilot_server.config.settings import RedisSettings
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services import states, templates
from dopilot_server.services.executions import TaskOrigin, create_task, new_id
from dopilot_server.services.outbox import create_run_outbox
from sqlalchemy import func, select

from .conftest import Seeder, make_settings


def _settings(tmp_path):
    return make_settings(
        auth_on=False,
        logs_root=str(tmp_path / "logs"),
        artifacts_root=str(tmp_path / "art"),
    )


async def _seed_scheduling(maker, settings, *, max_concurrency: int, enabled: bool):
    """Node + artifact + template + schedule, all inside PostgreSQL."""
    async with maker() as session:
        seeder = Seeder(session, settings)
        await seeder.healthy_node()
        artifact = await seeder.build_artifact()
        template = await templates.create_template(
            session,
            {
                "name": "pg-conc-template",
                "build_artifact_id": artifact.id,
                "command": "scrapy crawl phase1",
                "node_strategy": "all",
            },
        )
        await session.commit()
        schedule = await sched_svc.create_schedule(
            session,
            {
                "name": "pg-conc-schedule",
                "execution_template_id": template.id,
                "trigger_type": "interval",
                "interval_seconds": 30,
                "enabled": enabled,
                "max_concurrency": max_concurrency,
            },
        )
        await session.commit()
        return template.id, schedule.id


async def _active_count(maker, schedule_id: str) -> int:
    from dopilot_server.models.execution import Task

    async with maker() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Task)
                    .where(
                        Task.schedule_id == schedule_id,
                        Task.status.in_(states.TASK_ACTIVE),
                    )
                )
            ).scalar_one()
        )


async def _task_count(maker, schedule_id: str) -> int:
    from dopilot_server.models.execution import Task

    async with maker() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.schedule_id == schedule_id)
                )
            ).scalar_one()
        )


def _dispatcher(maker, redis):
    return CommandDispatcher(maker, CommandProducer(redis, RedisSettings()))


# --- TC-12: two concurrent trigger-now, one slot ----------------------------


async def test_concurrent_trigger_now_row_lock(pg_sessionmaker, exec_redis, tmp_path):
    settings = _settings(tmp_path)
    _tpl_id, schedule_id = await _seed_scheduling(
        pg_sessionmaker, settings, max_concurrency=1, enabled=True
    )
    dispatcher = _dispatcher(pg_sessionmaker, exec_redis)

    async def fire():
        async with pg_sessionmaker() as session:
            schedule = await sched_svc.get_schedule_or_404(session, schedule_id)
            try:
                await sched_svc.trigger_now(session, settings, dispatcher, schedule)
                return "ok"
            except Exception as exc:  # noqa: BLE001 - classify below
                return getattr(exc, "code", type(exc).__name__)

    results = await asyncio.gather(fire(), fire())
    assert sorted(results) == ["ok", "schedule.concurrency_limit"], results
    # The winner must really hold the slot (a no_target task would not).
    assert await _active_count(pg_sessionmaker, schedule_id) == 1


# --- TC-13: the limit is re-read UNDER the lock ------------------------------


async def test_limit_change_visible_under_lock(pg_sessionmaker, exec_redis, tmp_path):
    settings = _settings(tmp_path)
    _tpl_id, schedule_id = await _seed_scheduling(
        pg_sessionmaker, settings, max_concurrency=0, enabled=True
    )
    dispatcher = _dispatcher(pg_sessionmaker, exec_redis)

    async with pg_sessionmaker() as seed_session:
        request = ExecutionRunRequest(
            artifact_type="scrapy",
            target="demo:phase1",
            node_strategy="all",
            node_ids=[],
            params={},
        )
        task = create_task(
            seed_session,
            request,
            TaskOrigin(
                source=states.TASK_SOURCE_TIMER,
                schedule_id=schedule_id,
                schedule_generation=0,
                template_snapshot={},
            ),
        )
        task.status = states.TASK_RUNNING
        await seed_session.commit()

    async with pg_sessionmaker() as session_a:
        # A reads the schedule BEFORE the lock: max_concurrency is 0 here.
        stale = await sched_svc.get_schedule_or_404(session_a, schedule_id)
        assert stale.max_concurrency == 0

        async with pg_sessionmaker() as session_b:
            fresh = await sched_svc.get_schedule_or_404(session_b, schedule_id)
            await sched_svc.update_schedule(session_b, fresh, {"max_concurrency": 1})
            await session_b.commit()

        # A continues with its stale instance: the gate must use the LOCKED row.
        try:
            await sched_svc.trigger_now(session_a, settings, dispatcher, stale)
            raise AssertionError("expected the tightened limit to reject this firing")
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "code", None) == "schedule.concurrency_limit", exc

    assert await _task_count(pg_sessionmaker, schedule_id) == 1


# --- TC-14: backlog coalesce is evaluated INSIDE the locked region -----------


async def test_timer_coalesce_sees_backlog_committed_under_lock(
    pg_sessionmaker, exec_redis, tmp_path
):
    settings = _settings(tmp_path)
    _tpl_id, schedule_id = await _seed_scheduling(
        pg_sessionmaker, settings, max_concurrency=0, enabled=True
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def transaction_a():
        """Hold the schedule row, create an UNDISPATCHED task, then commit."""
        async with pg_sessionmaker() as session:
            slot = await sched_svc.acquire_firing_slot(
                session,
                schedule_id,
                raise_on_full=False,
                require_enabled=True,
                coalesce_backlog=True,
            )
            assert slot.granted is True
            request = ExecutionRunRequest(
                artifact_type="scrapy",
                target="demo:phase1",
                node_strategy="all",
                node_ids=[],
                params={},
            )
            task = create_task(
                session,
                request,
                TaskOrigin(
                    source=states.TASK_SOURCE_TRIGGER_NOW,
                    schedule_id=schedule_id,
                    schedule_generation=0,
                    template_snapshot={},
                ),
            )
            await session.flush()
            create_run_outbox(
                session,
                task_id=task.id,
                execution_id=new_id(),
                agent_id="agent-1",
                payload={},
                manual=True,
            )
            entered.set()
            await release.wait()
            await session.commit()

    async def transaction_b():
        async with pg_sessionmaker() as session:
            return await sched_svc.acquire_firing_slot(
                session,
                schedule_id,
                raise_on_full=False,
                require_enabled=True,
                coalesce_backlog=True,
            )

    a = asyncio.create_task(transaction_a())
    await entered.wait()
    b = asyncio.create_task(transaction_b())
    await asyncio.sleep(0.3)
    # B must be parked on the row lock, not already past the backlog check.
    assert not b.done()
    release.set()
    await a
    slot = await b

    assert slot.granted is False
    assert slot.skip_reason == sched_svc.SKIP_BACKLOG

    # And the real timer path creates nothing on top of A's task.
    dispatcher = _dispatcher(pg_sessionmaker, exec_redis)
    async with pg_sessionmaker() as session:
        schedule = await sched_svc.get_schedule_or_404(session, schedule_id)
        assert await sched_svc.fire_timer(session, settings, dispatcher, schedule) is None
    assert await _task_count(pg_sessionmaker, schedule_id) == 1
