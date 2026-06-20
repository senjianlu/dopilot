"""Command-outbox service tests (phase 1.5; phase-1.7 task/execution naming)."""

from __future__ import annotations

from dopilot_protocol import StopIntent
from dopilot_server.models.command_outbox import (
    OUTBOX_CANCELED,
    OUTBOX_PENDING,
    OUTBOX_SENT,
    CommandOutbox,
)
from dopilot_server.models.execution import Execution, Task
from dopilot_server.services import outbox, states
from dopilot_server.services.executions import new_id
from sqlalchemy import select


async def _seed_task(
    session,
    *,
    target="demo:phase1",
    status=states.TASK_QUEUED,
    schedule_id=None,
):
    task = Task(
        id=new_id(),
        artifact_type="scrapy",
        target=target,
        status=status,
        params={},
        schedule_id=schedule_id,
    )
    session.add(task)
    execution = Execution(
        id=new_id(),
        task_id=task.id,
        agent_id="agent-1",
        status=states.EXEC_PENDING,
        error_detail={},
    )
    session.add(execution)
    return task, execution


async def test_create_run_outbox_same_tx(db_session):
    task, execution = await _seed_task(db_session)
    row = outbox.create_run_outbox(
        db_session,
        task_id=task.id,
        execution_id=execution.id,
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
    task, execution = await _seed_task(db_session)
    pending = outbox.create_run_outbox(
        db_session,
        task_id=task.id,
        execution_id=execution.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    sent = outbox.create_stop_outbox(
        db_session,
        task_id=task.id,
        execution_id=execution.id,
        agent_id="agent-1",
        intent=StopIntent.cancel,
    )
    sent.status = OUTBOX_SENT  # already delivered -> must NOT be canceled
    await db_session.commit()

    count = await outbox.cancel_unsent_outbox(db_session, task.id)
    await db_session.commit()
    assert count == 1

    rows = {
        r.command_id: r.status
        for r in (
            await db_session.execute(
                select(CommandOutbox).where(
                    CommandOutbox.task_id == task.id
                )
            )
        ).scalars()
    }
    assert rows[pending.command_id] == OUTBOX_CANCELED
    assert rows[sent.command_id] == OUTBOX_SENT


async def test_coalesce_true_for_undispatched_backlog(db_session):
    # queued task + a still-pending outbox row = undispatched backlog -> coalesce.
    task, execution = await _seed_task(
        db_session, status=states.TASK_QUEUED, schedule_id="sched-A"
    )
    outbox.create_run_outbox(
        db_session,
        task_id=task.id,
        execution_id=execution.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    await db_session.commit()
    assert (
        await outbox.has_undispatched_backlog_for_schedule(db_session, "sched-A")
        is True
    )
    # a different schedule has no backlog
    assert (
        await outbox.has_undispatched_backlog_for_schedule(db_session, "other")
        is False
    )


async def test_coalesce_false_when_running(db_session):
    # decision #2: a running task must NOT suppress a new timer firing.
    task, execution = await _seed_task(
        db_session, status=states.TASK_RUNNING, schedule_id="sched-B"
    )
    row = outbox.create_run_outbox(
        db_session,
        task_id=task.id,
        execution_id=execution.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    row.status = OUTBOX_SENT
    await db_session.commit()
    assert (
        await outbox.has_undispatched_backlog_for_schedule(db_session, "sched-B")
        is False
    )


async def test_coalesce_false_when_queued_but_dispatched(db_session):
    # queued task whose command already reached Redis (outbox sent) is NOT
    # backlog -> do not coalesce.
    task, execution = await _seed_task(
        db_session, status=states.TASK_QUEUED, schedule_id="sched-C"
    )
    row = outbox.create_run_outbox(
        db_session,
        task_id=task.id,
        execution_id=execution.id,
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    row.status = OUTBOX_SENT
    await db_session.commit()
    assert (
        await outbox.has_undispatched_backlog_for_schedule(db_session, "sched-C")
        is False
    )
