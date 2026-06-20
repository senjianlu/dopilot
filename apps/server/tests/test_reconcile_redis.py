"""Heartbeat / event-stall reconcile tests (phase 1.5; phase-1.7 naming).

A parent run is a :class:`Task`; an atomic unit is an :class:`Execution`. The
``execution_log_files`` index keeps the wire seam columns ``execution_id``
(= task id) and ``attempt_id`` (= atomic execution id).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from dopilot_server.models.command_outbox import CommandOutbox
from dopilot_server.models.execution import (
    Execution,
    ExecutionLogFile,
    Task,
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
    exec_status=states.EXEC_RUNNING,
    task_status=states.TASK_RUNNING,
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
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=task_status, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id=agent_id,
        status=exec_status, error_detail={},
        started_at=now - timedelta(seconds=last_event_age),
        last_event_at=now - timedelta(seconds=last_event_age),
    )
    session.add(execution)
    session.add(
        ExecutionLogFile(
            execution_id=task.id, attempt_id=execution.id, stream="log",
            storage_path="/tmp/x.log", size_bytes=0, last_pulled_offset=0,
            status=states.LOG_ACTIVE,
        )
    )
    await session.commit()
    return node, task, execution


async def _stop_outbox(session, attempt_id):
    return (
        await session.execute(
            select(CommandOutbox).where(
                CommandOutbox.attempt_id == attempt_id,
                CommandOutbox.type == "stop",
            )
        )
    ).scalars().all()


async def _execution(session, execution_id):
    res = await session.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    return res.scalar_one()


async def _task(session, task_id):
    res = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    return res.scalar_one()


async def test_heartbeat_timeout_marks_lost_no_stop(db_session, settings):
    _settings(settings, hb_timeout=30)
    now = datetime.now(UTC)
    _node, task, execution = await _seed(db_session, now, last_seen_age=120)

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.heartbeat_lost == 1 and report.reclaim_stops == 0
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_LOST
    assert e.lost_reason == "heartbeat_timeout"
    # task rolled up to lost
    t = await _task(db_session, task.id)
    assert t.status == states.TASK_LOST
    # NO stop command (agent unreachable)
    assert await _stop_outbox(db_session, execution.id) == []


async def test_event_stall_sets_one_shot_alert(db_session, settings):
    _settings(settings, hb_timeout=30, stall=60, lost_after=600)
    now = datetime.now(UTC)
    _node, _t, execution = await _seed(
        db_session, now, last_seen_age=5, last_event_age=120
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.stalled == 1 and report.event_stall_lost == 0
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_RUNNING  # NOT terminal
    assert e.stalled_at is not None


async def test_event_stall_past_threshold_lost_and_reclaim(db_session, settings):
    _settings(settings, hb_timeout=30, stall=60, lost_after=300)
    now = datetime.now(UTC)
    _node, _t, execution = await _seed(
        db_session, now, last_seen_age=5, last_event_age=600
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.event_stall_lost == 1 and report.reclaim_stops == 1
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_LOST and e.lost_reason == "event_stall"
    # a stop(reclaim) command was enqueued
    stops = await _stop_outbox(db_session, execution.id)
    assert len(stops) == 1 and stops[0].intent == "reclaim"


async def test_terminal_execution_short_circuits(db_session, settings):
    _settings(settings, hb_timeout=30)
    now = datetime.now(UTC)
    _node, _t, execution = await _seed(
        db_session, now, last_seen_age=120,
        exec_status=states.EXEC_FINISHED, task_status=states.TASK_COMPLETE,
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    # finished execution is not active -> not selected -> no server-lost
    assert report.heartbeat_lost == 0
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_FINISHED


async def test_fresh_heartbeat_and_recent_event_no_action(db_session, settings):
    _settings(settings, hb_timeout=30, stall=300, lost_after=900)
    now = datetime.now(UTC)
    _node, _t, execution = await _seed(
        db_session, now, last_seen_age=2, last_event_age=2
    )
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    assert (report.heartbeat_lost, report.event_stall_lost, report.stalled) == (0, 0, 0)
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_RUNNING and e.stalled_at is None
