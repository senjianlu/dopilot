"""Heartbeat / event-stall reconcile tests (phase 1.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from dopilot_server.models.command_outbox import CommandOutbox
from dopilot_server.models.execution import (
    Execution,
    ExecutionAttempt,
    ExecutionLogFile,
)
from dopilot_server.models.node import Node
from dopilot_server.redis.reconcile import reconcile_once
from dopilot_server.services import states
from dopilot_server.services.executions import new_id
from sqlalchemy import select


def _settings(s, *, hb_timeout=30, stall=300, lost_after=900):
    s.agents.heartbeat_timeout_seconds = hb_timeout
    s.agents.stalled_attempt_seconds = stall
    s.agents.lost_after_stalled_seconds = lost_after
    return s


async def _seed(
    session,
    now,
    *,
    agent_id="agent-1",
    last_seen_age=0.0,
    last_event_age=0.0,
    attempt_status=states.ATTEMPT_RUNNING,
    exec_status=states.EXEC_RUNNING,
):
    node = Node(
        id=uuid.uuid4(),
        agent_id=agent_id,
        endpoint=f"http://{agent_id}:6800",
        status="healthy",
        capabilities={"scrapy": True},
        health={},
        last_seen_at=now - timedelta(seconds=last_seen_age),
    )
    session.add(node)
    execution = Execution(
        id=new_id(), task_type="scrapy", target="demo:phase1",
        status=exec_status, params={},
    )
    session.add(execution)
    attempt = ExecutionAttempt(
        id=new_id(), execution_id=execution.id, agent_id=agent_id,
        status=attempt_status, error_detail={},
        started_at=now - timedelta(seconds=last_event_age),
        last_event_at=now - timedelta(seconds=last_event_age),
    )
    session.add(attempt)
    session.add(
        ExecutionLogFile(
            execution_id=execution.id, attempt_id=attempt.id, stream="log",
            storage_path="/tmp/x.log", size_bytes=0, last_pulled_offset=0,
            status=states.LOG_ACTIVE,
        )
    )
    await session.commit()
    return node, execution, attempt


async def _stop_outbox(session, attempt_id):
    return (
        await session.execute(
            select(CommandOutbox).where(
                CommandOutbox.attempt_id == attempt_id,
                CommandOutbox.type == "stop",
            )
        )
    ).scalars().all()


async def _attempt(session, attempt_id):
    res = await session.execute(
        select(ExecutionAttempt).where(ExecutionAttempt.id == attempt_id)
    )
    return res.scalar_one()


async def _execution(session, execution_id):
    res = await session.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    return res.scalar_one()


async def test_heartbeat_timeout_marks_lost_no_stop(db_session, settings):
    _settings(settings, hb_timeout=30)
    now = datetime.now(UTC)
    _node, execution, attempt = await _seed(db_session, now, last_seen_age=120)

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.heartbeat_lost == 1 and report.reclaim_stops == 0
    a = await _attempt(db_session, attempt.id)
    assert a.status == states.ATTEMPT_LOST
    assert a.lost_reason == "heartbeat_timeout"
    # execution rolled up to lost
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_LOST
    # NO stop command (agent unreachable)
    assert await _stop_outbox(db_session, attempt.id) == []


async def test_event_stall_sets_one_shot_alert(db_session, settings):
    _settings(settings, hb_timeout=30, stall=60, lost_after=600)
    now = datetime.now(UTC)
    _node, _e, attempt = await _seed(
        db_session, now, last_seen_age=5, last_event_age=120
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.stalled == 1 and report.event_stall_lost == 0
    a = await _attempt(db_session, attempt.id)
    assert a.status == states.ATTEMPT_RUNNING  # NOT terminal
    assert a.stalled_at is not None


async def test_event_stall_past_threshold_lost_and_reclaim(db_session, settings):
    _settings(settings, hb_timeout=30, stall=60, lost_after=300)
    now = datetime.now(UTC)
    _node, execution, attempt = await _seed(
        db_session, now, last_seen_age=5, last_event_age=600
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.event_stall_lost == 1 and report.reclaim_stops == 1
    a = await _attempt(db_session, attempt.id)
    assert a.status == states.ATTEMPT_LOST and a.lost_reason == "event_stall"
    # a stop(reclaim) command was enqueued
    stops = await _stop_outbox(db_session, attempt.id)
    assert len(stops) == 1 and stops[0].intent == "reclaim"


async def test_terminal_attempt_short_circuits(db_session, settings):
    _settings(settings, hb_timeout=30)
    now = datetime.now(UTC)
    _node, _e, attempt = await _seed(
        db_session, now, last_seen_age=120,
        attempt_status=states.ATTEMPT_FINISHED, exec_status=states.EXEC_COMPLETE,
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    # finished attempt is not active -> not selected -> no server-lost
    assert report.heartbeat_lost == 0
    a = await _attempt(db_session, attempt.id)
    assert a.status == states.ATTEMPT_FINISHED


async def test_fresh_heartbeat_and_recent_event_no_action(db_session, settings):
    _settings(settings, hb_timeout=30, stall=300, lost_after=900)
    now = datetime.now(UTC)
    _node, _e, attempt = await _seed(
        db_session, now, last_seen_age=2, last_event_age=2
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    assert (report.heartbeat_lost, report.event_stall_lost, report.stalled) == (0, 0, 0)
    a = await _attempt(db_session, attempt.id)
    assert a.status == states.ATTEMPT_RUNNING and a.stalled_at is None
