"""Command dispatcher tests (phase 1.5) — drive try_dispatch/_process_row/_tick.

Phase-1.7 task/execution naming: a parent run is a :class:`Task`, an atomic unit
is an :class:`Execution`. The outbox row keeps the wire seam columns
``execution_id`` (= task id) and ``attempt_id`` (= execution id).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dopilot_protocol import AgentCommand, command_stream, from_stream_entry
from dopilot_server.config.settings import RedisSettings
from dopilot_server.models.command_outbox import (
    OUTBOX_CANCELED,
    OUTBOX_FAILED,
    OUTBOX_FAILED_RETRYABLE,
    OUTBOX_SENT,
    CommandOutbox,
)
from dopilot_server.models.execution import Execution, Task
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import outbox, states
from dopilot_server.services.executions import new_id
from sqlalchemy import select


async def _seed_run(
    session,
    *,
    agent_id="agent-1",
    task_status=states.TASK_QUEUED,
    exec_status=states.EXEC_PENDING,
    manual=True,
):
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=task_status, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id=agent_id,
        status=exec_status, error_detail={},
    )
    session.add(execution)
    row = outbox.create_run_outbox(
        session,
        execution_id=task.id,
        attempt_id=execution.id,
        agent_id=agent_id,
        payload={"project": "demo", "spider": "phase1"},
        manual=manual,
    )
    await session.commit()
    return task, execution, row


def _dispatcher(fake, test_sessionmaker) -> CommandDispatcher:
    producer = CommandProducer(fake, RedisSettings())
    return CommandDispatcher(test_sessionmaker, producer)


async def test_try_dispatch_happy_path(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    _task, execution, row = await _seed_run(db_session)
    disp = _dispatcher(fake, test_sessionmaker)

    result = await disp.try_dispatch(db_session, row)
    await db_session.commit()

    assert result.outcome == "sent"
    assert row.status == OUTBOX_SENT
    assert row.redis_msg_id is not None
    # the command really landed on the agent's command stream
    entries = await fake.entries(command_stream("agent-1"))
    assert len(entries) == 1
    cmd = from_stream_entry(AgentCommand, entries[0][1])
    # wire seam: attempt_id is the atomic execution id
    assert cmd.attempt_id == execution.id
    assert cmd.type.value == "run"
    assert cmd.payload["spider"] == "phase1"


async def test_xadd_failure_marks_retryable(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    fake.fail_xadd = True
    _t, _e, row = await _seed_run(db_session)
    disp = _dispatcher(fake, test_sessionmaker)

    result = await disp.try_dispatch(db_session, row)
    assert result.outcome == "retry"
    assert row.status == OUTBOX_FAILED_RETRYABLE
    assert row.retry_count == 1


async def test_manual_give_up_on_fail(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    fake.fail_xadd = True
    _t, _e, row = await _seed_run(db_session)
    disp = _dispatcher(fake, test_sessionmaker)

    result = await disp.try_dispatch(db_session, row, give_up_on_fail=True)
    assert result.outcome == "failed"
    assert row.status == OUTBOX_FAILED
    assert row.last_error == "dispatch_unavailable"


async def test_canceled_row_not_dispatched(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    _t, _e, row = await _seed_run(db_session)
    # cancel before dispatch (row.execution_id is the seam = task id)
    await outbox.cancel_unsent_outbox(db_session, row.execution_id)
    await db_session.commit()
    disp = _dispatcher(fake, test_sessionmaker)

    result = await disp.try_dispatch(db_session, row)
    assert result.outcome == "skipped"
    assert row.status == OUTBOX_CANCELED
    # nothing XADDed
    assert await fake.xlen(command_stream("agent-1")) == 0


async def test_run_short_circuit_on_terminal_task(
    db_session, fake_redis, test_sessionmaker
):
    fake = fake_redis()
    # manual run failed earlier -> task terminal, but a pending row lingers
    _t, _e, row = await _seed_run(db_session, task_status=states.TASK_FAILED)
    disp = _dispatcher(fake, test_sessionmaker)

    result = await disp.try_dispatch(db_session, row)
    assert result.outcome == "skipped"
    assert row.status == OUTBOX_CANCELED
    assert await fake.xlen(command_stream("agent-1")) == 0


async def test_give_up_past_deadline_fails_task(
    db_session, fake_redis, test_sessionmaker
):
    fake = fake_redis()
    task, execution, row = await _seed_run(db_session)
    # backdate the give-up deadline so the row is past it
    row.give_up_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    disp = _dispatcher(fake, test_sessionmaker)

    await disp._process_row(db_session, row)
    await db_session.commit()

    assert row.status == OUTBOX_FAILED
    assert row.last_error == "dispatch_timeout"
    refreshed_exec = (
        await db_session.execute(
            select(Execution).where(Execution.id == execution.id)
        )
    ).scalar_one()
    assert refreshed_exec.status == states.EXEC_FAILED
    assert refreshed_exec.error_code == "dispatch_timeout"
    refreshed_task = (
        await db_session.execute(
            select(Task).where(Task.id == task.id)
        )
    ).scalar_one()
    assert refreshed_task.status == states.TASK_FAILED
    # never XADDed
    assert await fake.xlen(command_stream("agent-1")) == 0


async def test_tick_dispatches_pending_rows(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    _t, _e, row = await _seed_run(db_session)
    disp = _dispatcher(fake, test_sessionmaker)

    await disp._tick()

    # row sent (re-read on a fresh session)
    async with test_sessionmaker() as s:
        persisted = (
            await s.execute(
                select(CommandOutbox).where(CommandOutbox.command_id == row.command_id)
            )
        ).scalar_one()
        assert persisted.status == OUTBOX_SENT
    assert await fake.xlen(command_stream("agent-1")) == 1


async def test_retry_exhaustion_fails_run_task(
    db_session, fake_redis, test_sessionmaker
):
    fake = fake_redis()
    fake.fail_xadd = True
    task, _execution, row = await _seed_run(db_session)
    row.max_retry = 1  # exhaust immediately
    await db_session.commit()
    disp = _dispatcher(fake, test_sessionmaker)

    await disp._process_row(db_session, row)
    await db_session.commit()

    assert row.status == OUTBOX_FAILED
    refreshed_task = (
        await db_session.execute(
            select(Task).where(Task.id == task.id)
        )
    ).scalar_one()
    assert refreshed_task.status == states.TASK_FAILED
