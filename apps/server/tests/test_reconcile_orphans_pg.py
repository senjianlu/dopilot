"""Task-level orphan repair under REAL PostgreSQL (rawf 2026-09-02, TC-13/14).

SQLite compiles ``FOR UPDATE`` away and its ``NOT EXISTS`` planning differs, so
the dialect path and the terminal-writer serialization are only observable
here. Fails (never skips) without ``DOPILOT_TEST_DATABASE_URL`` — see the
``pg_sessionmaker`` fixture.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from dopilot_server.models.execution import Execution, Task
from dopilot_server.models.node import Node
from dopilot_server.redis.reconcile import REPAIR_KEY, reconcile_once
from dopilot_server.services import executions as svc
from dopilot_server.services import states
from dopilot_server.services.executions import new_id
from sqlalchemy import select

from .conftest import make_settings


def _settings(tmp_path):
    s = make_settings(
        auth_on=False,
        logs_root=str(tmp_path / "logs"),
        artifacts_root=str(tmp_path / "art"),
    )
    s.agents.heartbeat_timeout_seconds = 30
    s.agents.stalled_attempt_seconds = 300
    s.agents.lost_after_stalled_seconds = 3600
    return s


async def _seed_stuck(maker, now):
    """Production shape: queued task, its only execution finished 7 days ago
    (started_at == finished_at, no running event), task started_at None."""
    age = now - timedelta(days=7)
    async with maker() as session:
        session.add(
            Node(
                id=uuid.uuid4(),
                agent_id="agent-1",
                endpoint="agent://agent-1",
                status="healthy",
                capabilities={"scrapy": True},
                health={},
                last_seen_at=now,
            )
        )
        task = Task(
            id=new_id(), artifact_type="scrapy", target="demo:phase1",
            status=states.TASK_QUEUED, params={},
            created_at=age - timedelta(seconds=21),
        )
        session.add(task)
        await session.flush()  # FK: PostgreSQL enforces executions.task_id -> tasks.id
        execution = Execution(
            id=new_id(), task_id=task.id, agent_id="agent-1",
            status=states.EXEC_FINISHED, error_detail={},
            started_at=age, last_event_at=age, finished_at=age,
        )
        session.add(execution)
        await session.commit()
        return task.id, execution.id


async def _task(maker, task_id):
    async with maker() as session:
        return (
            await session.execute(select(Task).where(Task.id == task_id))
        ).scalar_one()


async def _execution(maker, execution_id):
    async with maker() as session:
        return (
            await session.execute(select(Execution).where(Execution.id == execution_id))
        ).scalar_one()


async def test_orphan_repair_on_postgres(pg_sessionmaker, tmp_path):
    # TC-13: the NOT EXISTS candidate query + FOR UPDATE / populate_existing
    # re-read work under the PostgreSQL dialect and repair the stuck row.
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    task_id, execution_id = await _seed_stuck(pg_sessionmaker, now)

    async with pg_sessionmaker() as session:
        report = await reconcile_once(session, settings, now=now)
        await session.commit()

    assert (report.orphan_rolled_up, report.orphan_lost) == (1, 0)
    assert report.repaired_task_ids == [task_id]
    t = await _task(pg_sessionmaker, task_id)
    e = await _execution(pg_sessionmaker, execution_id)
    assert t.status == states.TASK_COMPLETE
    assert t.started_at == e.started_at and t.finished_at == e.finished_at
    assert t.status_reason is None
    assert t.status_detail[REPAIR_KEY]["from"] == states.TASK_QUEUED
    assert t.status_detail[REPAIR_KEY]["to"] == states.TASK_COMPLETE

    # idempotent on the real dialect too
    async with pg_sessionmaker() as session:
        again = await reconcile_once(session, settings, now=now + timedelta(seconds=5))
        await session.commit()
    assert (again.orphan_rolled_up, again.orphan_lost, again.repaired_task_ids) == (0, 0, [])


async def test_orphan_repair_yields_to_concurrent_terminal_writer(pg_sessionmaker, tmp_path):
    # TC-14: session B holds the task row lock and commits a terminal
    # (``canceled``) while reconcile in session A is blocked on the lock; A must
    # re-read under the lock, see the terminal and skip — never overwrite it.
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    task_id, _execution_id = await _seed_stuck(pg_sessionmaker, now)

    async with pg_sessionmaker() as session_b:
        locked = await svc.get_task(session_b, task_id, for_update=True)
        assert locked is not None and locked.status == states.TASK_QUEUED

        async def run_reconcile():
            async with pg_sessionmaker() as session_a:
                report = await reconcile_once(session_a, settings, now=now)
                await session_a.commit()
                return report

        a = asyncio.create_task(run_reconcile())
        await asyncio.sleep(0.5)  # let A reach the row lock and block
        assert not a.done()

        locked.status = states.TASK_CANCELED
        locked.finished_at = now
        await session_b.commit()  # releases the lock -> A proceeds

        report = await asyncio.wait_for(a, timeout=10)

    assert (report.orphan_rolled_up, report.orphan_lost, report.repaired_task_ids) == (0, 0, [])
    t = await _task(pg_sessionmaker, task_id)
    assert t.status == states.TASK_CANCELED
    assert REPAIR_KEY not in (t.status_detail or {})
