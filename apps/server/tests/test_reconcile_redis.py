"""Heartbeat / event-stall reconcile tests (phase 1.5; phase-1.7 naming).

A parent run is a :class:`Task`; an atomic unit is an :class:`Execution`. The
``execution_log_files`` index carries the columns ``task_id`` (= Task.id) and
``execution_id`` (= Execution.id) (phase 2a clean-cut).
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
            task_id=task.id, execution_id=execution.id, stream="log",
            storage_path="/tmp/x.log", size_bytes=0, last_pulled_offset=0,
            status=states.LOG_ACTIVE,
        )
    )
    await session.commit()
    return node, task, execution


async def _stop_outbox(session, execution_id):
    return (
        await session.execute(
            select(CommandOutbox).where(
                CommandOutbox.execution_id == execution_id,
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


async def test_old_attempt_with_fresh_heartbeat_event_not_lost(db_session, settings):
    # TC-04: a LONG-RUNNING attempt (started far beyond lost_after) whose
    # last_event_at was just refreshed by an attempt.heartbeat is NOT stalled,
    # NOT lost, NOT reclaimed — runtime alone must never kill a healthy attempt.
    _settings(settings, hb_timeout=30, stall=300, lost_after=900)
    now = datetime.now(UTC)
    _node, _t, execution = await _seed(
        db_session, now, last_seen_age=2, last_event_age=30
    )
    e = await _execution(db_session, execution.id)
    e.started_at = now - timedelta(seconds=7200)  # running for 2h
    await db_session.commit()

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    assert (report.heartbeat_lost, report.event_stall_lost, report.stalled) == (0, 0, 0)
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_RUNNING and e.stalled_at is None
    assert await _stop_outbox(db_session, execution.id) == []

    # control: same 2h-old attempt with a STALE last_event_at is still caught.
    e.last_event_at = now - timedelta(seconds=1200)
    await db_session.commit()
    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    assert report.event_stall_lost == 1 and report.reclaim_stops == 1
    e = await _execution(db_session, execution.id)
    assert e.status == states.EXEC_LOST and e.lost_reason == "event_stall"


# ---- task-level orphan repair (active task, no active execution) ----
# (rawf 2026-09-02/fix-queued-task-rollup-and-orphan-repair, TC-07 .. TC-12)

from dopilot_server.redis.reconcile import (  # noqa: E402
    ORPHAN_NO_EXECUTION,
    REPAIR_KEY,
    RedisReconcileLoop,
)

SEVEN_DAYS = timedelta(days=7)


async def _seed_stuck(session, now, *, task_status=states.TASK_QUEUED, age=SEVEN_DAYS):
    """The 2026-08-26 production shape: task queued, its only execution finished
    with started_at == finished_at (no running event ever applied), task
    started_at None. Node heartbeat fresh."""
    node, task, execution = await _seed(
        session, now, last_seen_age=0,
        exec_status=states.EXEC_FINISHED, task_status=task_status,
    )
    execution.started_at = now - age
    execution.last_event_at = now - age
    execution.finished_at = now - age
    task.started_at = None
    await session.commit()
    return node, task, execution


def _zero(report):
    return (report.orphan_rolled_up, report.orphan_lost, list(report.repaired_task_ids))


async def test_orphan_all_terminal_rolls_up_with_execution_timeline(db_session, settings):
    # TC-07
    _settings(settings, hb_timeout=30, stall=300, lost_after=3600)
    now = datetime.now(UTC)
    _node, task, execution = await _seed_stuck(db_session, now)

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert (report.orphan_rolled_up, report.orphan_lost) == (1, 0)
    assert report.repaired_task_ids == [task.id]
    t = await _task(db_session, task.id)
    e = await _execution(db_session, execution.id)
    assert t.status == states.TASK_COMPLETE
    assert t.started_at is not None and t.started_at == e.started_at
    assert t.finished_at is not None and t.finished_at == e.finished_at
    assert t.status_reason is None
    repair = t.status_detail[REPAIR_KEY]
    assert repair["from"] == states.TASK_QUEUED and repair["to"] == states.TASK_COMPLETE
    assert repair["reason"] == "no_active_execution" and repair["executions"] == 1
    assert repair["repaired_at"] == now.isoformat()


async def test_orphan_rollup_precedence_failed_over_finished(db_session, settings):
    # TC-08: running task, executions [failed, finished] -> failed; finished_at
    # is the latest execution finish.
    _settings(settings, hb_timeout=30, stall=300, lost_after=3600)
    now = datetime.now(UTC)
    _node, task, e_finished = await _seed_stuck(
        db_session, now, task_status=states.TASK_RUNNING, age=timedelta(hours=2)
    )
    e_failed = Execution(
        id=new_id(), task_id=task.id, agent_id="agent-1",
        status=states.EXEC_FAILED, error_detail={},
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1),
    )
    db_session.add(e_failed)
    await db_session.commit()

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert (report.orphan_rolled_up, report.orphan_lost) == (1, 0)
    t = await _task(db_session, task.id)
    assert t.status == states.TASK_FAILED
    assert t.finished_at == (await _execution(db_session, e_failed.id)).finished_at
    assert t.status_detail[REPAIR_KEY]["from"] == states.TASK_RUNNING


async def test_orphan_not_selected_while_an_execution_is_active(db_session, settings):
    # TC-09: [finished, pending] -> the NOT EXISTS predicate excludes the task;
    # the fresh pending execution is also not stalled/lost by the execution pass.
    _settings(settings, hb_timeout=30, stall=300, lost_after=3600)
    now = datetime.now(UTC)
    _node, task, _finished = await _seed_stuck(db_session, now)
    pending = Execution(
        id=new_id(), task_id=task.id, agent_id="agent-1",
        status=states.EXEC_PENDING, error_detail={}, created_at=now,
    )
    db_session.add(pending)
    await db_session.commit()

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert _zero(report) == (0, 0, [])
    assert (report.heartbeat_lost, report.event_stall_lost, report.stalled) == (0, 0, 0)
    t = await _task(db_session, task.id)
    assert t.status == states.TASK_QUEUED and t.started_at is None
    assert REPAIR_KEY not in (t.status_detail or {})
    assert (await _execution(db_session, pending.id)).status == states.EXEC_PENDING


async def test_orphan_zero_execution_respects_observation_window(db_session, settings):
    # TC-10: zero-execution queued tasks — young one untouched, old one -> lost.
    _settings(settings, hb_timeout=30, stall=300, lost_after=3600)
    now = datetime.now(UTC)
    young = Task(
        id=new_id(), artifact_type="scrapy", target="demo:young",
        status=states.TASK_QUEUED, params={}, created_at=now - timedelta(seconds=60),
    )
    old = Task(
        id=new_id(), artifact_type="scrapy", target="demo:old",
        status=states.TASK_QUEUED, params={}, created_at=now - timedelta(hours=2),
    )
    db_session.add_all([young, old])
    await db_session.commit()

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert (report.orphan_rolled_up, report.orphan_lost) == (0, 1)
    assert report.repaired_task_ids == [old.id]
    y = await _task(db_session, young.id)
    assert y.status == states.TASK_QUEUED and REPAIR_KEY not in (y.status_detail or {})
    o = await _task(db_session, old.id)
    assert o.status == states.TASK_LOST and o.status_reason == ORPHAN_NO_EXECUTION
    assert o.finished_at == now
    assert o.status_detail[REPAIR_KEY]["executions"] == 0
    assert o.status_detail[REPAIR_KEY]["to"] == states.TASK_LOST


async def test_orphan_terminal_tasks_untouched_and_repair_is_idempotent(db_session, settings):
    # TC-11: terminal tasks (complete / lost / no_target) are never selected;
    # a second pass after the repair is a no-op.
    _settings(settings, hb_timeout=30, stall=300, lost_after=3600)
    now = datetime.now(UTC)
    complete = Task(
        id=new_id(), artifact_type="scrapy", target="demo:complete",
        status=states.TASK_COMPLETE, params={}, status_detail={"keep": 1},
        created_at=now - SEVEN_DAYS, finished_at=now - SEVEN_DAYS,
    )
    db_session.add(complete)
    db_session.add(Execution(
        id=new_id(), task_id=complete.id, agent_id="agent-1",
        status=states.EXEC_FINISHED, error_detail={},
        started_at=now - SEVEN_DAYS, finished_at=now - SEVEN_DAYS,
    ))
    lost = Task(
        id=new_id(), artifact_type="scrapy", target="demo:lost",
        status=states.TASK_LOST, params={}, status_reason="manual",
        created_at=now - SEVEN_DAYS, finished_at=now - SEVEN_DAYS,
    )
    no_target = Task(
        id=new_id(), artifact_type="scrapy", target="demo:no-target",
        status=states.TASK_NO_TARGET, params={}, status_reason=states.TASK_NO_TARGET,
        status_detail={"healthy_count": 0}, created_at=now - SEVEN_DAYS,
    )
    db_session.add_all([lost, no_target])
    await db_session.commit()
    _node, stuck, _e = await _seed_stuck(db_session, now)

    first = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    assert (first.orphan_rolled_up, first.orphan_lost) == (1, 0)
    assert first.repaired_task_ids == [stuck.id]

    second = await reconcile_once(db_session, settings, now=now + timedelta(seconds=5))
    await db_session.commit()
    assert _zero(second) == (0, 0, [])

    c = await _task(db_session, complete.id)
    assert c.status == states.TASK_COMPLETE and c.status_detail == {"keep": 1}
    lo = await _task(db_session, lost.id)
    assert lo.status == states.TASK_LOST and lo.status_reason == "manual"
    assert REPAIR_KEY not in (lo.status_detail or {})
    nt = await _task(db_session, no_target.id)
    assert nt.status == states.TASK_NO_TARGET
    assert nt.status_detail == {"healthy_count": 0}
    s = await _task(db_session, stuck.id)
    assert s.status == states.TASK_COMPLETE
    assert s.status_detail[REPAIR_KEY]["repaired_at"] == now.isoformat()


async def test_orphan_repair_and_outcome_recorded_in_same_tick(
    db_session, exec_settings, seeder, test_sessionmaker
):
    # TC-12: a schedule-bound stuck task is repaired AND its (non-erroneous)
    # outcome recorded in the same RedisReconcileLoop tick, resetting the
    # schedule's consecutive error count.
    from dopilot_server.services import executions as svc
    from dopilot_server.services import schedules as sched_svc

    from .test_outcomes import _schedule

    exec_settings.agents.lost_after_stalled_seconds = 3600
    sched = await _schedule(db_session, seeder)
    sched.consecutive_error_count = 2
    await db_session.commit()

    now = datetime.now(UTC)
    finished_at = now - SEVEN_DAYS
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=states.TASK_QUEUED, params={}, source=states.TASK_SOURCE_TIMER,
        schedule_id=sched.id,
        schedule_generation=int(sched.outcome_generation or 0),
        created_at=finished_at - timedelta(seconds=21),
    )
    db_session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id="agent-1",
        status=states.EXEC_FINISHED, error_detail={},
        started_at=finished_at, finished_at=finished_at,
    )
    db_session.add(execution)
    log_file = svc.create_log_file(db_session, exec_settings, task, execution)
    log_file.status = states.LOG_COMPLETE
    log_file.finished_at = finished_at
    await db_session.commit()

    loop = RedisReconcileLoop(test_sessionmaker, exec_settings)
    await loop._tick()

    async with test_sessionmaker() as s:
        t = (await s.execute(select(Task).where(Task.id == task.id))).scalar_one()
        assert t.status == states.TASK_COMPLETE
        assert t.status_detail[REPAIR_KEY]["from"] == states.TASK_QUEUED
        assert t.outcome_recorded_at is not None and t.outcome_erroneous is False
        fresh = await sched_svc.get_schedule(s, sched.id)
        assert fresh.consecutive_error_count == 0
