"""Outcome recorder + schedule auto-disable (log-flood guard).

TC-15 (via states), TC-18, TC-19, TC-19b, TC-19c, TC-20, TC-20b, TC-20c,
TC-21, TC-23 (ledger side).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from dopilot_protocol import (
    AgentEvent,
    AgentEventType,
    AgentLogEvent,
    StopIntent,
)
from dopilot_server.models.execution import Execution, ExecutionLogFile, Task
from dopilot_server.models.notification import (
    TYPE_LOG_FLOOD,
    TYPE_SCHEDULE_AUTO_DISABLED,
    Notification,
)
from dopilot_server.models.scheduling import Schedule, ScheduleOutcomeLedger
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.redis.reconcile import finalize_drained_logs, mark_lost
from dopilot_server.services import executions as svc
from dopilot_server.services import maintenance, outbox, states
from dopilot_server.services.events import apply_event
from dopilot_server.services.executions import new_id
from dopilot_server.services.logs import OUTCOME_SEALED, apply_log_event
from dopilot_server.services.outcomes import record_task_outcomes
from dopilot_server.services.schedules import update_schedule
from dopilot_server.services.states import (
    execution_is_erroneous,
    task_is_erroneous,
)
from sqlalchemy import select

from .test_schedules import _template_row

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# --- TC-18: pure judgement ------------------------------------------------------------


def test_execution_is_erroneous_matrix():
    def ex(status, **kw):
        base = {"status": status, "error_code": None, "error_count": None,
                "finish_reason": None, "log_bytes": None, "id": "e"}
        base.update(kw)
        return _Obj(**base)

    def lf(reason):
        return _Obj(log_integrity="truncated", truncation_reason=reason)

    cases = [
        (ex("failed"), None, True),
        (ex("lost"), None, True),
        (ex("finished", error_count=0), None, False),
        (ex("finished", error_count=3), None, True),
        (ex("finished", finish_reason="closespider_errorcount"), None, True),
        (ex("finished"), lf("size-cap"), True),
        (ex("finished"), lf("maintenance"), False),
        (ex("finished", error_code="log_flood"), None, True),
        (ex("canceled", finish_reason="shutdown", error_count=2), None, False),
        (ex("canceled"), lf("size-cap"), True),
    ]
    for execution, log_file, expected in cases:
        assert execution_is_erroneous(execution, log_file, 0) is expected, execution.__dict__
    # agent-reported log_bytes at/over the cap is erroneous (cap 0 = never)
    assert execution_is_erroneous(ex("finished", log_bytes=10**9), None, 1024) is True
    assert execution_is_erroneous(ex("finished", log_bytes=10**9), None, 0) is False
    # task with no executions: judged on its own status
    assert task_is_erroneous(_Obj(status="failed"), []) is True
    assert task_is_erroneous(_Obj(status="complete"), []) is False
    assert task_is_erroneous(_Obj(status="complete"), [ex("finished", error_count=1)]) is True


# --- helpers ----------------------------------------------------------------------------


async def _schedule(session, seeder, *, threshold=3, enabled=True) -> Schedule:
    template = await _template_row(session, seeder, name=f"tpl-{new_id()[:8]}")
    sched = Schedule(
        name=f"sched-{new_id()[:6]}", execution_template_id=template.id,
        trigger_type="interval", interval_seconds=30, enabled=enabled,
    )
    session.add(sched)
    await session.commit()
    return sched


async def _task(
    session, settings, sched: Schedule | None, *, status="failed", exec_status="failed",
    source=states.TASK_SOURCE_TIMER, finished_at=None, log_status="complete",
    error_count=None, finish_reason=None, generation=None, agent_id="agent-1",
    with_execution=True, log_bytes=None,
) -> tuple[Task, Execution | None, ExecutionLogFile | None]:
    finished_at = finished_at or NOW - timedelta(minutes=5)
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1", status=status, params={},
        source=source, schedule_id=sched.id if sched else None,
        schedule_generation=(generation if generation is not None
                             else (int(sched.outcome_generation or 0) if sched else None)),
        finished_at=finished_at, created_at=finished_at - timedelta(minutes=1),
    )
    session.add(task)
    execution = None
    log_file = None
    if with_execution:
        execution = Execution(
            id=new_id(), task_id=task.id, agent_id=agent_id, status=exec_status,
            error_detail={}, error_count=error_count, finish_reason=finish_reason,
            finished_at=finished_at, log_bytes=log_bytes,
        )
        session.add(execution)
        log_file = svc.create_log_file(session, settings, task, execution)
        log_file.status = log_status
        log_file.finished_at = finished_at if log_status == "complete" else None
    await session.commit()
    return task, execution, log_file


async def _ledger(session, sched) -> list[ScheduleOutcomeLedger]:
    return list(
        (
            await session.execute(
                select(ScheduleOutcomeLedger)
                .where(ScheduleOutcomeLedger.schedule_id == sched.id)
                .order_by(ScheduleOutcomeLedger.finished_at.desc())
            )
        ).scalars().all()
    )


async def _refresh(session, obj):
    await session.refresh(obj)
    return obj


# --- TC-19: three failures -> disabled, idempotent -------------------------------------


async def test_three_consecutive_failures_disable_schedule(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 3
    sched = await _schedule(db_session, seeder)
    tasks = []
    for i in range(3):
        t, _e, _lf = await _task(
            db_session, exec_settings, sched, finished_at=NOW - timedelta(minutes=10 - i)
        )
        tasks.append(t)
    disabled = await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    assert disabled == [sched.id]
    for t in tasks:
        await _refresh(db_session, t)
        assert t.outcome_recorded_at is not None and t.outcome_erroneous is True
    await _refresh(db_session, sched)
    assert sched.enabled is False and sched.auto_disabled_at is not None
    assert sched.consecutive_error_count == 3
    reason = sched.auto_disabled_reason
    assert reason["consecutive_errors"] == 3 and len(reason["task_ids"]) == 3
    notes = list((await db_session.execute(
        select(Notification).where(Notification.type == TYPE_SCHEDULE_AUTO_DISABLED)
    )).scalars().all())
    assert len(notes) == 1 and notes[0].severity == "error"
    assert notes[0].payload["schedule_id"] == sched.id
    # idempotent second run
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == []
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 3


# --- TC-19b: trigger_now tasks count too ------------------------------------------------


async def test_trigger_now_tasks_count(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 3
    sched = await _schedule(db_session, seeder)
    for i, source in enumerate(
        [states.TASK_SOURCE_TRIGGER_NOW, states.TASK_SOURCE_TIMER, states.TASK_SOURCE_TRIGGER_NOW]
    ):
        await _task(db_session, exec_settings, sched, source=source,
                    finished_at=NOW - timedelta(minutes=10 - i))
    disabled = await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    assert disabled == [sched.id]
    assert len(await _ledger(db_session, sched)) == 3
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 3 and sched.enabled is False


# --- TC-19c: stats end-to-end via apply_event -------------------------------------------


def _terminal_event(execution, **kw) -> AgentEvent:
    return AgentEvent(
        event_id=new_id(), agent_id=execution.agent_id, task_id=execution.task_id,
        execution_id=execution.id, type=AgentEventType.finished, created_at="t", **kw,
    )


async def test_stats_drive_auto_disable_end_to_end(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 3
    sched = await _schedule(db_session, seeder)
    stats = [
        {"error_count": 91, "finish_reason": "finished"},
        {"error_count": 0, "finish_reason": "closespider_errorcount"},
        {"error_count": 1, "finish_reason": "finished"},
    ]
    executions = []
    for i, st in enumerate(stats):
        _t, e, lf = await _task(
            db_session, exec_settings, sched, status="running", exec_status="running",
            log_status="complete", finished_at=NOW - timedelta(minutes=10 - i),
        )
        out = await apply_event(db_session, _terminal_event(e, **st), f"m-{i}")
        assert out == "applied"
        await db_session.commit()
        executions.append(e)
    for e, st in zip(executions, stats, strict=True):
        await _refresh(db_session, e)
        assert (e.error_count, e.finish_reason) == (st["error_count"], st["finish_reason"])
        assert e.status == "finished"
    disabled = await record_task_outcomes(
        db_session, exec_settings, now=NOW + timedelta(minutes=30)
    )
    await db_session.commit()
    assert disabled == [sched.id]
    assert all(r.erroneous for r in await _ledger(db_session, sched))

    # manual re-enable, then a clean finished run -> ledger false, count 0
    await update_schedule(db_session, sched, {"enabled": True})
    await db_session.commit()
    _t, e, lf = await _task(
        db_session, exec_settings, sched, status="running", exec_status="running",
        finished_at=NOW + timedelta(minutes=40),
    )
    ok_event = _terminal_event(e, error_count=0, finish_reason="finished")
    await apply_event(db_session, ok_event, "m-ok")
    await db_session.commit()
    assert await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(hours=2)) == []
    await db_session.commit()
    await _refresh(db_session, sched)
    rows = await _ledger(db_session, sched)
    assert rows[0].erroneous is False and rows[0].generation == 1
    assert sched.consecutive_error_count == 0 and sched.enabled is True


# --- TC-20: success resets; direct tasks ignored; threshold 0 off; multi-exec -----------


async def test_reset_ignore_and_threshold_zero(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 3
    sched = await _schedule(db_session, seeder)
    seq = [("failed", "failed"), ("failed", "failed"), ("complete", "finished"),
           ("failed", "failed"), ("failed", "failed")]
    for i, (ts, es) in enumerate(seq):
        await _task(db_session, exec_settings, sched, status=ts, exec_status=es,
                    error_count=0 if es == "finished" else None,
                    finished_at=NOW - timedelta(minutes=20 - i))
        await record_task_outcomes(db_session, exec_settings, now=NOW)
        await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 2 and sched.enabled is True

    # (b) direct-artifact failure does not count
    await _task(db_session, exec_settings, sched, source=states.TASK_SOURCE_DIRECT,
                finished_at=NOW - timedelta(minutes=1))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 2 and len(await _ledger(db_session, sched)) == 5

    # (c) threshold 0 -> never disables
    exec_settings.scheduler.auto_disable_after_errors = 0
    for i in range(5):
        await _task(db_session, exec_settings, sched, finished_at=NOW + timedelta(minutes=i + 1))
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(hours=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.enabled is True and sched.consecutive_error_count == 7

    # (d) one task, two executions: finished + lost -> erroneous
    exec_settings.scheduler.auto_disable_after_errors = 100
    sched2 = await _schedule(db_session, seeder)
    t, e1, _lf1 = await _task(db_session, exec_settings, sched2, status="lost",
                              exec_status="finished", error_count=0,
                              finished_at=NOW - timedelta(days=2))
    e2 = Execution(id=new_id(), task_id=t.id, agent_id="agent-2", status="lost",
                   error_detail={}, finished_at=NOW - timedelta(days=2))
    db_session.add(e2)
    lf2 = svc.create_log_file(db_session, exec_settings, t, e2)
    lf2.status = "complete"
    await db_session.commit()
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t)
    assert t.outcome_erroneous is True
    await _refresh(db_session, sched2)
    assert sched2.consecutive_error_count == 1


# --- TC-20b: order-independent ledger + soft-lost policy --------------------------------


async def test_ledger_is_order_independent(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    exec_settings.logs.log_drain_timeout_seconds = 300  # keep 'draining' inside the window
    sched = await _schedule(db_session, seeder)
    # (a) failure A (log still active), success B (sealed) -> count 0 both times
    a, _ea, lfa = await _task(db_session, exec_settings, sched, log_status="active",
                              finished_at=NOW - timedelta(minutes=2))
    b, _eb, _lfb = await _task(db_session, exec_settings, sched, status="complete",
                               exec_status="finished", error_count=0,
                               finished_at=NOW - timedelta(minutes=1))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, a)
    assert a.outcome_recorded_at is None  # still draining
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 0
    lfa.status = "complete"
    await db_session.commit()
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, a)
    assert a.outcome_erroneous is True
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 0  # A is older than success B

    # (b) B..E four failures recorded, then the OLDEST failure A' arrives late -> 5
    sched2 = await _schedule(db_session, seeder)
    late, _el, lfl = await _task(db_session, exec_settings, sched2, log_status="active",
                                 finished_at=NOW - timedelta(minutes=4))
    for i in range(4):
        await _task(db_session, exec_settings, sched2,
                    finished_at=NOW - timedelta(minutes=3) + timedelta(seconds=30 * i))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, sched2)
    assert sched2.consecutive_error_count == 4 and sched2.enabled is True
    lfl.status = "complete"
    await db_session.commit()
    disabled = await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    assert disabled == [sched2.id]
    await _refresh(db_session, sched2)
    assert sched2.consecutive_error_count == 5 and sched2.enabled is False


async def test_soft_lost_policy(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    exec_settings.scheduler.lost_outcome_grace_seconds = 86400
    sched = await _schedule(db_session, seeder)
    # (c) pure server-lost: not reclaimed -> not recorded, not sealed
    t, e, lf = await _task(db_session, exec_settings, sched, status="lost", exec_status="lost",
                           log_status="finalizing", finished_at=NOW - timedelta(hours=1))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t)
    await _refresh(db_session, lf)
    assert t.outcome_recorded_at is None and lf.status == "finalizing"

    # (d) reclaim issued + drain passed -> recorded as erroneous; then the agent
    # overrides lost with finished -> stamp cleared -> re-judged as success
    outbox.create_stop_outbox(db_session, task_id=t.id, execution_id=e.id,
                              agent_id="agent-1", intent=StopIntent.reclaim)
    await db_session.commit()
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t)
    await _refresh(db_session, sched)
    assert t.outcome_erroneous is True and sched.consecutive_error_count == 1
    ev = AgentEvent(event_id=new_id(), agent_id="agent-1", task_id=t.id, execution_id=e.id,
                    type=AgentEventType.finished, error_count=0, finish_reason="finished",
                    created_at="t")
    out = await apply_event(db_session, ev, "m-override")
    await db_session.commit()
    assert out == "override_lost"
    await _refresh(db_session, t)
    assert t.status == "complete" and t.outcome_recorded_at is None
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=5))
    await db_session.commit()
    await _refresh(db_session, t)
    await _refresh(db_session, sched)
    assert t.outcome_erroneous is False and sched.consecutive_error_count == 0
    rows = await _ledger(db_session, sched)
    assert len(rows) == 1 and rows[0].erroneous is False

    # (e) pure server-lost past the grace -> recorded erroneous
    t2, _e2, _lf2 = await _task(db_session, exec_settings, sched, status="lost", exec_status="lost",
                                log_status="finalizing", finished_at=NOW - timedelta(days=2))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t2)
    assert t2.outcome_erroneous is True


# --- TC-20c: ledger survives task retention + self-trims --------------------------------


async def test_ledger_independent_of_task_retention(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    exec_settings.logs.retention_days = 0
    sched = await _schedule(db_session, seeder)
    for i in range(3):
        await _task(
            db_session, exec_settings, sched, finished_at=NOW - timedelta(days=3, minutes=i)
        )
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    summary = await maintenance.cleanup_terminal_data(
        db_session, exec_settings, cutoff=NOW, dry_run=False
    )
    assert summary.as_dict()["tasks"] == 3
    assert (await db_session.execute(select(Task))).scalars().all() == []
    assert len(await _ledger(db_session, sched)) == 3
    for i in range(2):
        await _task(db_session, exec_settings, sched, finished_at=NOW - timedelta(minutes=5 - i))
    disabled = await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    assert disabled == [sched.id]
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 5

    # self-trim: 150 more rows -> max(100, 10) kept
    sched3 = await _schedule(db_session, seeder)
    for i in range(150):
        await _task(db_session, exec_settings, sched3, status="complete", exec_status="finished",
                    error_count=0, finished_at=NOW - timedelta(seconds=1000 - i))
    await record_task_outcomes(db_session, exec_settings, now=NOW, limit=1000)
    await db_session.commit()
    assert len(await _ledger(db_session, sched3)) == 100


# --- TC-21: every terminal write path + sealing ----------------------------------------


async def _log_event(execution, offset, content: bytes) -> AgentLogEvent:
    return AgentLogEvent(
        agent_id=execution.agent_id, task_id=execution.task_id, execution_id=execution.id,
        offset=offset, content_b64=base64.b64encode(content).decode("ascii"),
        size_bytes=len(content), created_at="t",
    )


async def test_terminal_paths_and_sealing(db_session, exec_settings, seeder, fake_redis):
    exec_settings.scheduler.auto_disable_after_errors = 100
    exec_settings.logs.max_file_bytes = 1024
    exec_settings.logs.log_drain_timeout_seconds = 30
    sched = await _schedule(db_session, seeder)

    # (a) dispatch timeout path
    t, e, lf = await _task(db_session, exec_settings, sched, status="queued", exec_status="pending",
                           log_status="active", finished_at=None)
    row = outbox.create_run_outbox(db_session, task_id=t.id, execution_id=e.id, agent_id="agent-1",
                                   payload={}, manual=True)
    await db_session.commit()
    from dopilot_server.config.settings import RedisSettings
    from dopilot_server.redis.commands import CommandProducer

    dispatcher = CommandDispatcher(None, CommandProducer(fake_redis(), RedisSettings()))
    await dispatcher._fail_execution_dispatch_timeout(db_session, row)
    await db_session.commit()
    await _refresh(db_session, t)
    assert t.status == "failed"
    lf.status = "complete"
    await db_session.commit()
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t)
    await _refresh(db_session, sched)
    assert t.outcome_erroneous is True and sched.consecutive_error_count == 1

    # (b) finished first, truncation after, then finalize -> erroneous (not success)
    t2, e2, lf2 = await _task(db_session, exec_settings, sched, status="complete",
                              exec_status="finished", error_count=0, log_status="active",
                              finished_at=NOW - timedelta(seconds=5))
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == []
    await _refresh(db_session, t2)
    assert t2.outcome_recorded_at is None  # draining, inside the window
    out = await apply_log_event(db_session, exec_settings, await _log_event(e2, 0, b"x" * 2048))
    await db_session.commit()
    assert out == "truncated"
    lf2 = await db_session.get(ExecutionLogFile, (t2.id, e2.id, "log"))
    lf2.status = "complete"
    await db_session.commit()
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t2)
    assert t2.outcome_erroneous is True

    # (c)/(d) fallback: active log, inside window -> wait; past drain+60 -> seal + record
    t3, e3, lf3 = await _task(db_session, exec_settings, sched, status="complete",
                              exec_status="finished", error_count=0, log_status="active",
                              finished_at=NOW - timedelta(seconds=50))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await _refresh(db_session, t3)
    assert t3.outcome_recorded_at is None
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(seconds=60))
    await db_session.commit()
    await _refresh(db_session, t3)
    lf3 = await db_session.get(ExecutionLogFile, (t3.id, e3.id, "log"))
    await db_session.refresh(lf3)
    assert t3.outcome_erroneous is False and lf3.status == "complete"
    # (e) late increment after the seal: dropped, integrity + outcome unchanged
    out = await apply_log_event(db_session, exec_settings, await _log_event(e3, 0, b"y" * 4096))
    assert out == OUTCOME_SEALED
    await db_session.refresh(lf3)
    assert lf3.log_integrity == "complete" and lf3.size_bytes == 0
    await _refresh(db_session, t3)
    assert t3.outcome_erroneous is False

    # (f) finished event with log_bytes over the cap, no increments at all -> erroneous
    t4, e4, lf4 = await _task(db_session, exec_settings, sched, status="complete",
                              exec_status="finished", error_count=0, log_bytes=1025,
                              finished_at=NOW - timedelta(minutes=10))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t4)
    assert t4.outcome_erroneous is True

    # reconcile.mark_lost path -> lost -> (reclaim + drain) -> erroneous
    t5, e5, lf5 = await _task(db_session, exec_settings, sched, status="running",
                              exec_status="running", log_status="active", finished_at=None)
    assert await mark_lost(db_session, e5, "heartbeat_timeout", NOW - timedelta(hours=1))
    outbox.create_stop_outbox(db_session, task_id=t5.id, execution_id=e5.id, agent_id="agent-1",
                              intent=StopIntent.reclaim)
    await db_session.commit()
    await finalize_drained_logs(db_session, exec_settings)
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, t5)
    assert t5.status == "lost" and t5.outcome_erroneous is True


# --- TC-06b: log_flood terminal raises a notification once ----------------------------


async def test_log_flood_terminal_notifies_once(db_session, exec_settings, seeder, client):
    sched = await _schedule(db_session, seeder)
    _t, e, _lf = await _task(db_session, exec_settings, sched, status="running",
                             exec_status="running", log_status="active", finished_at=None)
    ev = AgentEvent(event_id=new_id(), agent_id="agent-1", task_id=e.task_id, execution_id=e.id,
                    type=AgentEventType.failed, error_code="log_flood",
                    error_detail={"log_bytes": 40000000, "cap": 33554432,
                                  "kill_escalation": "kill"},
                    log_bytes=40000000, created_at="t")
    assert await apply_event(db_session, ev, "flood-1") == "applied"
    await db_session.commit()
    ev2 = ev.model_copy(update={"event_id": new_id()})
    await apply_event(db_session, ev2, "flood-2")  # re-delivery: terminal skipped
    await db_session.commit()
    notes = list((await db_session.execute(
        select(Notification).where(Notification.type == TYPE_LOG_FLOOD)
    )).scalars().all())
    assert len(notes) == 1 and notes[0].severity == "warning"
    assert notes[0].payload["task_id"] == e.task_id and notes[0].payload["log_bytes"] == 40000000
    await _refresh(db_session, e)
    assert e.log_bytes == 40000000 and e.error_code == "log_flood"
    body = (await client.get("/api/v1/notifications")).json()
    assert any(n["type"] == TYPE_LOG_FLOOD for n in body["notifications"])


# --- TC-23: manual re-enable starts a new generation -------------------------------------


async def test_manual_reenable_starts_new_generation(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    exec_settings.logs.log_drain_timeout_seconds = 300  # keep 'draining' inside the window
    sched = await _schedule(db_session, seeder)
    for i in range(5):
        await _task(db_session, exec_settings, sched, finished_at=NOW - timedelta(minutes=10 - i))
    # an old lost task, NOT yet recorded (still draining), created in generation 0
    old_lost, old_e, old_lf = await _task(
        db_session, exec_settings, sched, status="lost", exec_status="lost",
        log_status="finalizing", finished_at=NOW - timedelta(minutes=3),
    )
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == [sched.id]
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.enabled is False and sched.consecutive_error_count == 5

    await update_schedule(db_session, sched, {"enabled": True})
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.enabled and sched.consecutive_error_count == 0
    assert sched.auto_disabled_at is None and sched.auto_disabled_reason is None
    assert sched.outcome_generation == 1

    # (a) new task (generation 1) fails -> count 1, not 6
    await _task(db_session, exec_settings, sched, finished_at=NOW + timedelta(minutes=1))
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=2))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 1 and sched.enabled is True

    # (b) the old lost task is overridden by finished AFTER the re-enable: its
    # finished_at is rewritten to now, but it stays in generation 0
    ev = AgentEvent(event_id=new_id(), agent_id="agent-1", task_id=old_lost.id,
                    execution_id=old_e.id, type=AgentEventType.finished, error_count=0,
                    created_at="t")
    await apply_event(db_session, ev, "late-override")
    await db_session.commit()
    # apply_event stamps the override with the wall clock; record past the
    # drain fallback so the (still finalizing) log gets sealed + recorded.
    await record_task_outcomes(
        db_session, exec_settings, now=datetime.now(UTC) + timedelta(minutes=10)
    )
    await db_session.commit()
    rows = await _ledger(db_session, sched)
    old_row = next(r for r in rows if r.task_id == old_lost.id)
    assert old_row.generation == 0 and old_row.erroneous is False
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 1  # generation-1 count untouched
