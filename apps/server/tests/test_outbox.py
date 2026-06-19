"""Command-outbox service tests (phase 1.5)."""

from __future__ import annotations

from dopilot_protocol import StopIntent
from dopilot_server.models.command_outbox import (
    OUTBOX_CANCELED,
    OUTBOX_PENDING,
    OUTBOX_SENT,
    CommandOutbox,
)
from dopilot_server.models.execution import Execution, ExecutionAttempt
from dopilot_server.services import outbox, states
from dopilot_server.services.executions import new_id
from sqlalchemy import select


async def _seed_execution(session, *, target="demo:phase1", status=states.EXEC_QUEUED):
    execution = Execution(
        id=new_id(), task_type="scrapy", target=target, status=status, params={}
    )
    session.add(execution)
    attempt = ExecutionAttempt(
        id=new_id(),
        execution_id=execution.id,
        agent_id="agent-1",
        status=states.ATTEMPT_PENDING,
        error_detail={},
    )
    session.add(attempt)
    return execution, attempt


async def test_create_run_outbox_same_tx(db_session):
    execution, attempt = await _seed_execution(db_session)
    row = outbox.create_run_outbox(
        db_session,
        execution_id=execution.id,
        attempt_id=attempt.id,
        agent_id="agent-1",
        payload={"project": "demo", "spider": "phase1"},
        manual=True,
    )
    await db_session.commit()

    persisted = (
        await db_session.execute(
            select(CommandOutbox).where(CommandOutbox.command_id == row.command_id)
        )
    ).scalar_one()
    assert persisted.status == OUTBOX_PENDING
    assert persisted.type == "run"
    assert persisted.payload["spider"] == "phase1"
    assert persisted.give_up_at is not None
    assert persisted.max_retry == 10


async def test_cancel_unsent_outbox_cas(db_session):
    execution, attempt = await _seed_execution(db_session)
    pending = outbox.create_run_outbox(
        db_session,
        execution_id=execution.id,
        attempt_id=attempt.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    sent = outbox.create_stop_outbox(
        db_session,
        execution_id=execution.id,
        attempt_id=attempt.id,
        agent_id="agent-1",
        intent=StopIntent.cancel,
    )
    sent.status = OUTBOX_SENT  # already delivered -> must NOT be canceled
    await db_session.commit()

    count = await outbox.cancel_unsent_outbox(db_session, execution.id)
    await db_session.commit()
    assert count == 1

    rows = {
        r.command_id: r.status
        for r in (
            await db_session.execute(
                select(CommandOutbox).where(
                    CommandOutbox.execution_id == execution.id
                )
            )
        ).scalars()
    }
    assert rows[pending.command_id] == OUTBOX_CANCELED
    assert rows[sent.command_id] == OUTBOX_SENT


async def test_coalesce_active_execution(db_session):
    await _seed_execution(db_session, target="sched-A", status=states.EXEC_QUEUED)
    await db_session.commit()
    assert await outbox.has_unterminated_for_target(db_session, "sched-A") is True
    assert await outbox.has_unterminated_for_target(db_session, "other") is False


async def test_coalesce_pending_outbox_on_terminal_execution(db_session):
    # execution terminal but a pending outbox row lingers -> still coalesces
    execution, attempt = await _seed_execution(
        db_session, target="sched-B", status=states.EXEC_FAILED
    )
    outbox.create_run_outbox(
        db_session,
        execution_id=execution.id,
        attempt_id=attempt.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    await db_session.commit()
    assert await outbox.has_unterminated_for_target(db_session, "sched-B") is True


async def test_coalesce_false_when_all_terminal(db_session):
    execution, attempt = await _seed_execution(
        db_session, target="sched-C", status=states.EXEC_COMPLETE
    )
    row = outbox.create_run_outbox(
        db_session,
        execution_id=execution.id,
        attempt_id=attempt.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    row.status = OUTBOX_SENT
    await db_session.commit()
    assert await outbox.has_unterminated_for_target(db_session, "sched-C") is False
