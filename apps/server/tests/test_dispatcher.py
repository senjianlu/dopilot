"""Command dispatcher tests (phase 1.5) — drive try_dispatch/_process_row/_tick.

Task/execution naming: a parent run is a :class:`Task`, an atomic unit is an
:class:`Execution`. The outbox row carries columns ``task_id`` (= Task.id) and
``execution_id`` (= Execution.id).
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
        task_id=task.id,
        execution_id=execution.id,
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
    assert cmd.execution_id == execution.id
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
    # cancel before dispatch (row.task_id is the parent task id)
    await outbox.cancel_unsent_outbox(db_session, row.task_id)
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


# --- TC-07 (fix-outbox-sent-oom): per-tick dispatch batch limit lives in SQL ----------


async def test_tick_dispatch_batch_limit_sql(
    db_session, fake_redis, test_sessionmaker, db_engine
):
    from sqlalchemy import event as sa_event

    fake = fake_redis()
    producer = CommandProducer(fake, RedisSettings())
    disp = CommandDispatcher(test_sessionmaker, producer, dispatch_batch_limit=2)
    base = datetime.now(UTC) - timedelta(seconds=60)
    rows = []
    for i, agent in enumerate(("ag-1", "ag-2", "ag-3")):
        _t, _e, row = await _seed_run(db_session, agent_id=agent, manual=False)
        row.created_at = base + timedelta(seconds=i)  # oldest first: ag-1, ag-2, ag-3
        rows.append(row)
    await db_session.commit()

    captured: list[tuple[str, object]] = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        captured.append((statement, parameters))

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", spy)
    try:
        await disp._tick()
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", spy)

    # exactly the two OLDEST rows were dispatched; the third is still pending
    row_ids = [r.command_id for r in rows]
    db_session.expire_all()
    statuses = [
        (await db_session.get(CommandOutbox, rid)).status for rid in row_ids
    ]
    assert statuses == [OUTBOX_SENT, OUTBOX_SENT, "pending"]
    assert len(await fake.entries(command_stream("ag-1"))) == 1
    assert len(await fake.entries(command_stream("ag-2"))) == 1
    assert await fake.entries(command_stream("ag-3")) == []
    # SQL-side proof: the dispatchable SELECT orders by created_at and LIMITs 2
    tick_selects = [
        (s, p)
        for s, p in captured
        if s.lstrip().upper().startswith("SELECT")
        and "command_outbox" in s
        and "ORDER BY" in s.upper()
    ]
    assert tick_selects, "dispatchable SELECT with ORDER BY not captured"
    stmt, params = tick_selects[0]
    upper = stmt.upper()
    assert "ORDER BY COMMAND_OUTBOX.CREATED_AT" in upper
    assert "LIMIT" in upper
    assert (2 in tuple(params)) or ("LIMIT 2" in upper), (
        f"LIMIT value 2 not found in stmt/params: {stmt!r} / {params!r}"
    )

    # the next tick picks up the remainder
    await disp._tick()
    db_session.expire_all()
    assert (await db_session.get(CommandOutbox, row_ids[2])).status == OUTBOX_SENT
