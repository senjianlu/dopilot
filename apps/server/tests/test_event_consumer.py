"""Server event-application + consumer tests (phase 1.5)."""

from __future__ import annotations

import uuid

from dopilot_protocol import (
    EVENT_GROUP,
    EVENT_STREAM,
    AgentEvent,
    AgentEventType,
    LostReason,
    to_stream_entry,
)
from dopilot_server.models.command_outbox import CommandOutbox
from dopilot_server.models.event_audit import (
    OUTCOME_APPLIED,
    OUTCOME_OVERRIDE_LOST,
    OUTCOME_RECLAIM_REQUESTED,
    OUTCOME_SKIPPED_DUP,
    OUTCOME_SKIPPED_TERMINAL,
)
from dopilot_server.models.execution import Execution, ExecutionAttempt
from dopilot_server.redis.consumers import EventConsumer
from dopilot_server.services import states
from dopilot_server.services.events import apply_event
from dopilot_server.services.executions import new_id
from sqlalchemy import select

RUNNING = states.ATTEMPT_RUNNING
LOST = states.ATTEMPT_LOST
FINISHED = states.ATTEMPT_FINISHED


async def _seed(session, *, exec_status=states.EXEC_QUEUED, attempt_status=states.ATTEMPT_PENDING):
    execution = Execution(
        id=new_id(), task_type="scrapy", target="demo:phase1",
        status=exec_status, params={},
    )
    session.add(execution)
    attempt = ExecutionAttempt(
        id=new_id(), execution_id=execution.id, agent_id="agent-1",
        status=attempt_status, error_detail={},
    )
    session.add(attempt)
    await session.commit()
    return execution, attempt


def _event(type_, attempt, **kw) -> AgentEvent:
    return AgentEvent(
        event_id=uuid.uuid4().hex,
        agent_id="agent-1",
        execution_id=attempt.execution_id,
        attempt_id=attempt.id,
        type=type_,
        created_at="t",
        **kw,
    )


async def _apply(session, type_, attempt, msg, **kw):
    return await apply_event(session, _event(type_, attempt, **kw), msg)


async def _reload(session, attempt):
    return (
        await session.execute(
            select(ExecutionAttempt).where(ExecutionAttempt.id == attempt.id)
        )
    ).scalar_one()


async def _reload_exec(session, execution_id):
    return (
        await session.execute(select(Execution).where(Execution.id == execution_id))
    ).scalar_one()


async def test_running_converges_execution_and_is_idempotent(db_session):
    execution, attempt = await _seed(db_session)
    out1 = await _apply(db_session, AgentEventType.running, attempt, "m1", remote_job_id="job-1")
    assert out1 == OUTCOME_APPLIED
    a = await _reload(db_session, attempt)
    assert a.status == RUNNING and a.remote_job_id == "job-1"
    assert (await _reload_exec(db_session, execution.id)).status == states.EXEC_RUNNING

    # duplicate running (different msg id) -> still running, no regression
    out2 = await _apply(db_session, AgentEventType.running, attempt, "m2")
    assert out2 == OUTCOME_APPLIED
    assert (await _reload(db_session, attempt)).status == RUNNING


async def test_running_then_finished_rolls_up_complete(db_session):
    execution, attempt = await _seed(
        db_session, attempt_status=RUNNING, exec_status=states.EXEC_RUNNING
    )
    await _apply(db_session, AgentEventType.finished, attempt, "m1", exit_code=0)
    assert (await _reload(db_session, attempt)).status == FINISHED
    assert (await _reload_exec(db_session, execution.id)).status == states.EXEC_COMPLETE


async def test_hard_terminal_not_regressed_by_lost(db_session):
    _e, attempt = await _seed(
        db_session, attempt_status=FINISHED, exec_status=states.EXEC_COMPLETE
    )
    out = await _apply(
        db_session, AgentEventType.lost, attempt, "m1",
        lost_reason=LostReason.heartbeat_timeout,
    )
    assert out == OUTCOME_SKIPPED_TERMINAL
    assert (await _reload(db_session, attempt)).status == FINISHED


async def test_server_lost_overridden_by_agent_terminal(db_session):
    execution, attempt = await _seed(
        db_session, attempt_status=LOST, exec_status=states.EXEC_RUNNING
    )
    a = await _reload(db_session, attempt)
    a.lost_reason = "heartbeat_timeout"
    await db_session.commit()

    out = await _apply(db_session, AgentEventType.finished, attempt, "m1", exit_code=0)
    assert out == OUTCOME_OVERRIDE_LOST
    a = await _reload(db_session, attempt)
    assert a.status == FINISHED and a.reconciled_from == "lost"
    # execution rolls up to complete (not lost)
    assert (await _reload_exec(db_session, execution.id)).status == states.EXEC_COMPLETE


async def test_duplicate_event_deduped(db_session):
    _e, attempt = await _seed(db_session)
    out1 = await _apply(db_session, AgentEventType.finished, attempt, "same-msg")
    await db_session.commit()
    out2 = await _apply(db_session, AgentEventType.running, attempt, "same-msg")
    assert out1 == OUTCOME_APPLIED
    assert out2 == OUTCOME_SKIPPED_DUP
    # the dup did not regress finished -> running
    assert (await _reload(db_session, attempt)).status == FINISHED


async def test_lost_reason_persisted_and_distinguishable(db_session):
    _e, attempt = await _seed(
        db_session, attempt_status=RUNNING, exec_status=states.EXEC_RUNNING
    )
    await _apply(
        db_session, AgentEventType.lost, attempt, "m1",
        lost_reason=LostReason.process_missing,
    )
    a = await _reload(db_session, attempt)
    assert a.status == LOST and a.lost_reason == "process_missing"
    assert LostReason(a.lost_reason).source == "agent"


async def test_lost_to_lost_agent_reason_wins(db_session):
    _e, attempt = await _seed(
        db_session, attempt_status=LOST, exec_status=states.EXEC_RUNNING
    )
    a = await _reload(db_session, attempt)
    a.lost_reason = "heartbeat_timeout"  # server-inferred first
    await db_session.commit()
    # later agent-reported lost upserts the reason (agent > server)
    await _apply(
        db_session, AgentEventType.lost, attempt, "m1",
        lost_reason=LostReason.state_missing,
    )
    assert (await _reload(db_session, attempt)).lost_reason == "state_missing"


async def _reclaim_stops(session, attempt_id):
    return (
        (
            await session.execute(
                select(CommandOutbox).where(
                    CommandOutbox.attempt_id == attempt_id,
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
    # attempt -> server enqueues stop(reclaim) and the attempt STAYS lost.
    _e, attempt = await _seed(
        db_session, attempt_status=LOST, exec_status=states.EXEC_RUNNING
    )
    a = await _reload(db_session, attempt)
    a.lost_reason = "heartbeat_timeout"
    await db_session.commit()

    out = await _apply(db_session, AgentEventType.running, attempt, "m1")
    await db_session.commit()
    assert out == OUTCOME_RECLAIM_REQUESTED
    assert (await _reload(db_session, attempt)).status == LOST  # NOT regressed
    stops = await _reclaim_stops(db_session, attempt.id)
    assert len(stops) == 1

    # idempotent: a second running event does not pile up another reclaim
    await _apply(db_session, AgentEventType.running, attempt, "m2")
    await db_session.commit()
    assert len(await _reclaim_stops(db_session, attempt.id)) == 1


async def test_execution_rerolls_from_lost_on_override(db_session):
    # execution already rolled up to EXEC_LOST (its only attempt was lost), then
    # the agent's real terminal overrides -> execution re-rolls to the terminal.
    execution, attempt = await _seed(
        db_session, attempt_status=LOST, exec_status=states.EXEC_LOST
    )
    out = await _apply(db_session, AgentEventType.finished, attempt, "m1", exit_code=0)
    assert out == OUTCOME_OVERRIDE_LOST
    assert (await _reload(db_session, attempt)).status == FINISHED
    assert (await _reload_exec(db_session, execution.id)).status == states.EXEC_COMPLETE


async def test_event_consumer_drains_stream(db_session, fake_redis, test_sessionmaker):
    fake = fake_redis()
    execution, attempt = await _seed(db_session)
    consumer = EventConsumer(test_sessionmaker, fake, consumer_name="server-1")
    await consumer.setup()

    run_ev = _event(AgentEventType.running, attempt, remote_job_id="job-1")
    fin_ev = _event(AgentEventType.finished, attempt, exit_code=0)
    await fake.xadd(EVENT_STREAM, to_stream_entry(run_ev))
    await fake.xadd(EVENT_STREAM, to_stream_entry(fin_ev))
    n = await consumer.drain_once()
    assert n == 2

    async with test_sessionmaker() as s:
        assert (await _reload(s, attempt)).status == FINISHED
        assert (await _reload_exec(s, execution.id)).status == states.EXEC_COMPLETE
    assert await fake.pending_count(EVENT_STREAM, EVENT_GROUP) == 0
