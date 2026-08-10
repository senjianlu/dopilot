"""Server event-application + consumer tests (phase 1.5; phase-1.7 naming).

A parent run is a :class:`Task`, an atomic unit is an :class:`Execution`. On the
agent wire (``AgentEvent``) the parent id is ``task_id`` and the atomic id is
``execution_id`` (phase 2a clean-cut).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dopilot_protocol import (
    EVENT_GROUP,
    EVENT_STREAM,
    AgentEvent,
    AgentEventType,
    LostReason,
    to_stream_entry,
)
from dopilot_server.models.command_outbox import OUTBOX_SENT, CommandOutbox
from dopilot_server.models.event_audit import (
    OUTCOME_APPLIED,
    OUTCOME_OVERRIDE_LOST,
    OUTCOME_RECLAIM_REQUESTED,
    OUTCOME_SKIPPED_DUP,
    OUTCOME_SKIPPED_TERMINAL,
    EventAudit,
)
from dopilot_server.models.execution import Execution, Task
from dopilot_server.redis.consumers import EventConsumer
from dopilot_server.services import states
from dopilot_server.services.events import (
    OUTCOME_HEARTBEAT,
    OUTCOME_SKIPPED_NO_ATTEMPT,
    apply_event,
)
from dopilot_server.services.executions import new_id
from sqlalchemy import select

RUNNING = states.EXEC_RUNNING
LOST = states.EXEC_LOST
FINISHED = states.EXEC_FINISHED


async def _seed(session, *, task_status=states.TASK_QUEUED, exec_status=states.EXEC_PENDING):
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=task_status, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id="agent-1",
        status=exec_status, error_detail={},
    )
    session.add(execution)
    await session.commit()
    return task, execution


def _event(type_, execution, **kw) -> AgentEvent:
    return AgentEvent(
        event_id=uuid.uuid4().hex,
        agent_id="agent-1",
        task_id=execution.task_id,
        execution_id=execution.id,
        type=type_,
        created_at="t",
        **kw,
    )


async def _apply(session, type_, execution, msg, **kw):
    return await apply_event(session, _event(type_, execution, **kw), msg)


async def _reload(session, execution):
    return (
        await session.execute(
            select(Execution).where(Execution.id == execution.id)
        )
    ).scalar_one()


async def _reload_task(session, task_id):
    return (
        await session.execute(select(Task).where(Task.id == task_id))
    ).scalar_one()


async def test_running_converges_task_and_is_idempotent(db_session):
    task, execution = await _seed(db_session)
    out1 = await _apply(db_session, AgentEventType.running, execution, "m1", remote_job_id="job-1")
    assert out1 == OUTCOME_APPLIED
    e = await _reload(db_session, execution)
    assert e.status == RUNNING and e.remote_job_id == "job-1"
    assert (await _reload_task(db_session, task.id)).status == states.TASK_RUNNING

    # duplicate running (different msg id) -> still running, no regression
    out2 = await _apply(db_session, AgentEventType.running, execution, "m2")
    assert out2 == OUTCOME_APPLIED
    assert (await _reload(db_session, execution)).status == RUNNING


async def test_running_then_finished_rolls_up_complete(db_session):
    task, execution = await _seed(
        db_session, exec_status=RUNNING, task_status=states.TASK_RUNNING
    )
    await _apply(db_session, AgentEventType.finished, execution, "m1", exit_code=0)
    assert (await _reload(db_session, execution)).status == FINISHED
    assert (await _reload_task(db_session, task.id)).status == states.TASK_COMPLETE


async def test_hard_terminal_not_regressed_by_lost(db_session):
    _t, execution = await _seed(
        db_session, exec_status=FINISHED, task_status=states.TASK_COMPLETE
    )
    out = await _apply(
        db_session, AgentEventType.lost, execution, "m1",
        lost_reason=LostReason.heartbeat_timeout,
    )
    assert out == OUTCOME_SKIPPED_TERMINAL
    assert (await _reload(db_session, execution)).status == FINISHED


async def test_server_lost_overridden_by_agent_terminal(db_session):
    task, execution = await _seed(
        db_session, exec_status=LOST, task_status=states.TASK_RUNNING
    )
    e = await _reload(db_session, execution)
    e.lost_reason = "heartbeat_timeout"
    await db_session.commit()

    out = await _apply(db_session, AgentEventType.finished, execution, "m1", exit_code=0)
    assert out == OUTCOME_OVERRIDE_LOST
    e = await _reload(db_session, execution)
    assert e.status == FINISHED and e.reconciled_from == "lost"
    # task rolls up to complete (not lost)
    assert (await _reload_task(db_session, task.id)).status == states.TASK_COMPLETE


async def test_duplicate_event_deduped(db_session):
    _t, execution = await _seed(db_session)
    out1 = await _apply(db_session, AgentEventType.finished, execution, "same-msg")
    await db_session.commit()
    out2 = await _apply(db_session, AgentEventType.running, execution, "same-msg")
    assert out1 == OUTCOME_APPLIED
    assert out2 == OUTCOME_SKIPPED_DUP
    # the dup did not regress finished -> running
    assert (await _reload(db_session, execution)).status == FINISHED


async def test_lost_reason_persisted_and_distinguishable(db_session):
    _t, execution = await _seed(
        db_session, exec_status=RUNNING, task_status=states.TASK_RUNNING
    )
    await _apply(
        db_session, AgentEventType.lost, execution, "m1",
        lost_reason=LostReason.process_missing,
    )
    e = await _reload(db_session, execution)
    assert e.status == LOST and e.lost_reason == "process_missing"
    assert LostReason(e.lost_reason).source == "agent"


async def test_lost_to_lost_agent_reason_wins(db_session):
    _t, execution = await _seed(
        db_session, exec_status=LOST, task_status=states.TASK_RUNNING
    )
    e = await _reload(db_session, execution)
    e.lost_reason = "heartbeat_timeout"  # server-inferred first
    await db_session.commit()
    # later agent-reported lost upserts the reason (agent > server)
    await _apply(
        db_session, AgentEventType.lost, execution, "m1",
        lost_reason=LostReason.state_missing,
    )
    assert (await _reload(db_session, execution)).lost_reason == "state_missing"


async def _reclaim_stops(session, execution_id):
    return (
        (
            await session.execute(
                select(CommandOutbox).where(
                    CommandOutbox.execution_id == execution_id,
                    CommandOutbox.type == "stop",
                    CommandOutbox.intent == "reclaim",
                )
            )
        )
        .scalars()
        .all()
    )


async def test_running_on_server_lost_requests_reclaim_keeps_lost(db_session):
    # cleanup-reconcile: agent recovers and re-emits running on a server-lost
    # execution -> server enqueues stop(reclaim) and the execution STAYS lost.
    _t, execution = await _seed(
        db_session, exec_status=LOST, task_status=states.TASK_RUNNING
    )
    e = await _reload(db_session, execution)
    e.lost_reason = "heartbeat_timeout"
    await db_session.commit()

    out = await _apply(db_session, AgentEventType.running, execution, "m1")
    await db_session.commit()
    assert out == OUTCOME_RECLAIM_REQUESTED
    assert (await _reload(db_session, execution)).status == LOST  # NOT regressed
    stops = await _reclaim_stops(db_session, execution.id)
    assert len(stops) == 1

    # idempotent: a second running event does not pile up another reclaim
    await _apply(db_session, AgentEventType.running, execution, "m2")
    await db_session.commit()
    assert len(await _reclaim_stops(db_session, execution.id)) == 1


async def _audit_rows(session, execution_id):
    return (
        (
            await session.execute(
                select(EventAudit).where(EventAudit.execution_id == execution_id)
            )
        )
        .scalars()
        .all()
    )


async def test_heartbeat_refreshes_stall_clock_without_audit(db_session):
    # TC-02: a heartbeat on a running execution refreshes last_event_at, clears
    # the stalled marker, changes no status, and writes NO audit row.
    _t, execution = await _seed(
        db_session, exec_status=RUNNING, task_status=states.TASK_RUNNING
    )
    e = await _reload(db_session, execution)
    stale = datetime(2020, 1, 1, tzinfo=UTC)
    e.last_event_at = stale
    e.stalled_at = stale
    await db_session.commit()

    out = await _apply(db_session, AgentEventType.heartbeat, execution, "m1")
    await db_session.commit()
    assert out == OUTCOME_HEARTBEAT
    e = await _reload(db_session, execution)
    assert e.status == RUNNING
    assert e.stalled_at is None
    last_event_at = e.last_event_at
    if last_event_at.tzinfo is None:
        last_event_at = last_event_at.replace(tzinfo=UTC)
    assert last_event_at > stale
    assert await _audit_rows(db_session, execution.id) == []


async def test_heartbeat_unknown_execution_skips_without_audit(db_session):
    # TC-03: heartbeat for an execution the server does not know -> no-op.
    ev = AgentEvent(
        event_id=uuid.uuid4().hex,
        agent_id="agent-1",
        task_id="no-such-task",
        execution_id="no-such-execution",
        type=AgentEventType.heartbeat,
        created_at="t",
    )
    out = await apply_event(db_session, ev, "m1")
    assert out == OUTCOME_SKIPPED_NO_ATTEMPT
    assert await _audit_rows(db_session, "no-such-execution") == []


async def test_heartbeat_on_server_lost_reclaims_at_most_once(db_session):
    # TC-11: a heartbeat on a server-lost execution proves the process is alive
    # -> exactly ONE stop(reclaim) ever, even after the first row turns `sent`
    # (the ever-issued dedupe is status-blind), and it stays lost.
    _t, execution = await _seed(
        db_session, exec_status=LOST, task_status=states.TASK_RUNNING
    )
    e = await _reload(db_session, execution)
    e.lost_reason = "heartbeat_timeout"
    await db_session.commit()

    out = await _apply(db_session, AgentEventType.heartbeat, execution, "m1")
    await db_session.commit()
    assert out == OUTCOME_RECLAIM_REQUESTED
    assert (await _reload(db_session, execution)).status == LOST  # NOT regressed
    stops = await _reclaim_stops(db_session, execution.id)
    assert len(stops) == 1
    audits = await _audit_rows(db_session, execution.id)
    assert [a.outcome for a in audits] == [OUTCOME_RECLAIM_REQUESTED]

    # first reclaim dispatched (sent) but no terminal yet -> the next periodic
    # heartbeat must NOT enqueue another stop nor write another audit row.
    stops[0].status = OUTBOX_SENT
    await db_session.commit()
    out = await _apply(db_session, AgentEventType.heartbeat, execution, "m2")
    await db_session.commit()
    assert out == OUTCOME_RECLAIM_REQUESTED
    assert len(await _reclaim_stops(db_session, execution.id)) == 1
    assert len(await _audit_rows(db_session, execution.id)) == 1


async def test_event_consumer_skips_unparseable_entry(
    db_session, fake_redis, test_sessionmaker
):
    # TC-12: a poison entry (e.g. an unknown event type from a newer agent) is
    # acked + skipped; later valid events still apply and nothing stays pending.
    fake = fake_redis()
    _t, execution = await _seed(db_session)
    consumer = EventConsumer(test_sessionmaker, fake, consumer_name="server-1")
    await consumer.setup()

    await fake.xadd(EVENT_STREAM, {b"data": b'{"type": "attempt.bogus"}'})
    fin_ev = _event(AgentEventType.finished, execution, exit_code=0)
    await fake.xadd(EVENT_STREAM, to_stream_entry(fin_ev))
    await consumer.drain_once()

    async with test_sessionmaker() as s:
        assert (await _reload(s, execution)).status == FINISHED
    assert await fake.pending_count(EVENT_STREAM, EVENT_GROUP) == 0


async def test_task_rerolls_from_lost_on_override(db_session):
    # task already rolled up to TASK_LOST (its only execution was lost), then the
    # agent's real terminal overrides -> task re-rolls to the terminal.
    task, execution = await _seed(
        db_session, exec_status=LOST, task_status=states.TASK_LOST
    )
    out = await _apply(db_session, AgentEventType.finished, execution, "m1", exit_code=0)
    assert out == OUTCOME_OVERRIDE_LOST
    assert (await _reload(db_session, execution)).status == FINISHED
    assert (await _reload_task(db_session, task.id)).status == states.TASK_COMPLETE


async def test_event_consumer_drains_stream(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    task, execution = await _seed(db_session)
    consumer = EventConsumer(test_sessionmaker, fake, consumer_name="server-1")
    await consumer.setup()

    run_ev = _event(AgentEventType.running, execution, remote_job_id="job-1")
    fin_ev = _event(AgentEventType.finished, execution, exit_code=0)
    await fake.xadd(EVENT_STREAM, to_stream_entry(run_ev))
    await fake.xadd(EVENT_STREAM, to_stream_entry(fin_ev))
    n = await consumer.drain_once()
    assert n == 2

    async with test_sessionmaker() as s:
        assert (await _reload(s, execution)).status == FINISHED
        assert (await _reload_task(s, task.id)).status == states.TASK_COMPLETE
    assert await fake.pending_count(EVENT_STREAM, EVENT_GROUP) == 0
