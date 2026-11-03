"""Schedule circuit breaker (decision 0025) on SQLite.

Covers the plan's TC-04 (classify), TC-05 (event), TC-06 (trip), TC-07 (gate),
TC-08 (half_open), TC-09 (escalat), TC-10 (reset / enable / artifact / view)
and TC-20 (boundary). Row-lock interleavings live in
``test_schedule_breaker_pg.py`` (SQLite compiles ``FOR UPDATE`` away).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from dopilot_server.config.settings import RedisSettings
from dopilot_server.errors import ApiError
from dopilot_server.models.execution import Execution, ExecutionLogFile, Task
from dopilot_server.models.notification import (
    TYPE_SCHEDULE_BREAKER_CLOSED,
    TYPE_SCHEDULE_BREAKER_HELD,
    TYPE_SCHEDULE_BREAKER_OPEN,
    Notification,
)
from dopilot_server.models.scheduling import ExecutionTemplate, Schedule, ScheduleOutcomeLedger
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import outcomes
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services.events import apply_event
from dopilot_server.services.executions import new_id
from dopilot_server.services.outcomes import record_task_outcomes
from dopilot_server.services.states import (
    execution_outcome_class,
    task_outcome_class,
)
from sqlalchemy import select

from .test_outcomes import NOW, _Obj, _refresh, _schedule, _task, _terminal_event


def _aw(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _close_to(actual: datetime | None, expected: datetime, slack: float = 5.0) -> bool:
    return actual is not None and abs((_aw(actual) - expected).total_seconds()) <= slack


async def _notes(session, type_: str) -> list[Notification]:
    return list(
        (await session.execute(select(Notification).where(Notification.type == type_)))
        .scalars()
        .all()
    )


async def _tasks_of(session, sched: Schedule) -> list[Task]:
    return list(
        (
            await session.execute(
                select(Task)
                .where(Task.schedule_id == sched.id)
                .order_by(Task.created_at.asc(), Task.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def _set(session, sched: Schedule, **fields) -> Schedule:
    for key, value in fields.items():
        setattr(sched, key, value)
    await session.commit()
    return sched


async def _btask(session, settings, sched, *, kind: str, finished_at=None, generation=None,
                 artifact_id=None):
    """A recorded-ready task of a given breaker class.

    ``kind``: ok | transient (finished + ERROR + crawler 'transient') | broken
    (stats-less failure) | canceled | no_target | lost.
    """
    finished_at = finished_at or NOW
    common = {"finished_at": finished_at, "generation": generation}
    if kind == "ok":
        t, e, lf = await _task(session, settings, sched, status="complete",
                               exec_status="finished", error_count=0,
                               finish_reason="finished", **common)
    elif kind == "transient":
        t, e, lf = await _task(session, settings, sched, status="complete",
                               exec_status="finished", error_count=2,
                               finish_reason="site_request_failed", **common)
        e.outcome_class = "transient"
    elif kind == "broken":
        t, e, lf = await _task(session, settings, sched, **common)
    elif kind == "canceled":
        t, e, lf = await _task(session, settings, sched, status="canceled",
                               exec_status="canceled", **common)
    elif kind == "no_target":
        t, e, lf = await _task(session, settings, sched, status="no_target",
                               with_execution=False, **common)
    elif kind == "lost":
        t, e, lf = await _task(session, settings, sched, status="lost", exec_status="lost",
                               **common)
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(kind)
    if artifact_id is not None:
        t.template_snapshot = {"build_artifact": {"id": artifact_id}}
    await session.commit()
    return t, e, lf


def _dispatcher(maker, redis) -> CommandDispatcher:
    return CommandDispatcher(maker, CommandProducer(redis, RedisSettings()))


async def _finish(session, task: Task, *, status: str, exec_status: str, error_count=None,
                  outcome_class=None, finished_at=None) -> None:
    """Drive a fire_timer-created task to a recorded-ready terminal."""
    finished_at = finished_at or datetime.now(UTC)
    task = await session.get(Task, task.id, populate_existing=True)
    task.status = status
    task.finished_at = finished_at
    for e in (await session.execute(select(Execution).where(Execution.task_id == task.id))
              ).scalars():
        e.status = exec_status
        e.finished_at = finished_at
        e.error_count = error_count
        e.finish_reason = "finished" if exec_status == "finished" else None
        e.outcome_class = outcome_class
    for lf in (await session.execute(
        select(ExecutionLogFile).where(ExecutionLogFile.task_id == task.id)
    )).scalars():
        lf.status = "complete"
        lf.finished_at = finished_at
    await session.commit()


# =========================================================================== #
# TC-04: classification matrix
# =========================================================================== #


def _ex(**kw):
    base = {"id": "x", "status": "finished", "error_code": None, "error_count": 0,
            "finish_reason": "finished", "log_bytes": None, "outcome_class": None}
    base.update(kw)
    return _Obj(**base)


def test_classify_server_judged_signals_override_crawler_transient():
    cap = 1000
    flood = _ex(status="failed", error_code="log_flood", outcome_class="transient")
    assert execution_outcome_class(flood, None, cap) == "broken"
    truncated = _ex(error_count=1, outcome_class="transient")
    lf = _Obj(log_integrity="truncated", truncation_reason="size-cap")
    assert execution_outcome_class(truncated, lf, cap) == "broken"
    at_cap = _ex(error_count=1, outcome_class="transient", log_bytes=cap)
    assert execution_outcome_class(at_cap, None, cap) == "broken"
    below_cap = _ex(error_count=1, outcome_class="transient", log_bytes=cap - 1)
    assert execution_outcome_class(below_cap, None, cap) == "transient"


def test_classify_cap_zero_never_judges_log_size():
    huge = 10**12
    failed = _ex(status="failed", error_count=None, finish_reason=None,
                 outcome_class="transient", log_bytes=huge)
    assert execution_outcome_class(failed, None, 0) == "transient"
    lost = _ex(status="lost", error_count=None, finish_reason=None, log_bytes=huge)
    assert execution_outcome_class(lost, None, 0) == "transient"


def test_classify_platform_failures_are_transient():
    assert execution_outcome_class(_ex(status="lost"), None, 0) == "transient"
    assert execution_outcome_class(
        _ex(status="failed", error_code="dispatch_unavailable"), None, 0
    ) == "transient"
    assert execution_outcome_class(
        _ex(status="failed", error_code="dispatch_timeout"), None, 0
    ) == "transient"


def test_classify_crawler_class_only_transient_softens():
    assert execution_outcome_class(_ex(error_count=3, outcome_class="transient"), None, 0) == (
        "transient"
    )
    for value in ("broken", "ok", None, "weird"):
        assert execution_outcome_class(_ex(error_count=3, outcome_class=value), None, 0) == (
            "broken"
        ), value
    stats_less_failure = _ex(status="failed", error_count=None, finish_reason=None)
    assert execution_outcome_class(stats_less_failure, None, 0) == "broken"
    assert execution_outcome_class(_ex(), None, 0) is None  # not erroneous


def test_classify_task_level():
    assert task_outcome_class(_Obj(status="complete"), [_ex()], {}, 0) == "ok"
    assert task_outcome_class(_Obj(status="canceled"), [_ex(status="canceled")], {}, 0) == (
        "neutral"
    )
    assert task_outcome_class(_Obj(status="no_target"), [], {}, 0) == "neutral"
    broken = _ex(id="b", status="failed", error_count=None, finish_reason=None)
    transient = _ex(id="t", error_count=1, outcome_class="transient")
    assert task_outcome_class(_Obj(status="failed"), [broken, transient], {}, 0) == "broken"
    assert task_outcome_class(_Obj(status="complete"), [transient], {}, 0) == "transient"


# =========================================================================== #
# TC-05: the event consumer stores the crawler class
# =========================================================================== #


async def test_event_stores_outcome_class(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    _t, e, _lf = await _task(db_session, exec_settings, sched, status="running",
                             exec_status="running")
    ev = _terminal_event(e, error_count=2, finish_reason="finished", outcome_class="transient")
    assert await apply_event(db_session, ev, "m-1") == "applied"
    await db_session.commit()
    await _refresh(db_session, e)
    assert e.outcome_class == "transient"


async def test_event_truncates_long_outcome_class(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    _t, e, _lf = await _task(db_session, exec_settings, sched, status="running",
                             exec_status="running")
    ev = _terminal_event(e, error_count=1, finish_reason="finished", outcome_class="t" * 200)
    await apply_event(db_session, ev, "m-2")
    await db_session.commit()
    await _refresh(db_session, e)
    assert e.outcome_class == "t" * 64


async def test_event_without_outcome_class_leaves_none(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    _t, e, _lf = await _task(db_session, exec_settings, sched, status="running",
                             exec_status="running")
    await apply_event(db_session, _terminal_event(e, error_count=0, finish_reason="finished"),
                      "m-3")
    await db_session.commit()
    await _refresh(db_session, e)
    assert e.outcome_class is None


# =========================================================================== #
# TC-06: tripping from closed
# =========================================================================== #


async def test_trip_transient_opens_without_touching_enabled(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    sched = await _schedule(db_session, seeder)
    for i in range(5):
        await _btask(db_session, exec_settings, sched, kind="transient",
                     finished_at=NOW - timedelta(minutes=10 - i))
    tripped = await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    assert tripped == [sched.id]
    await _refresh(db_session, sched)
    assert sched.enabled is True
    assert sched.breaker_state == "open" and sched.breaker_level == 0
    assert _aw(sched.breaker_retry_at) == NOW + timedelta(seconds=900)
    assert _aw(sched.breaker_opened_at) == NOW
    assert sched.breaker_reason["kind"] == "transient"
    notes = await _notes(db_session, TYPE_SCHEDULE_BREAKER_OPEN)
    assert len(notes) == 1 and notes[0].severity == "warning"
    assert notes[0].payload["schedule_id"] == sched.id and notes[0].payload["escalated"] is False
    rows = (await db_session.execute(
        select(ScheduleOutcomeLedger).where(ScheduleOutcomeLedger.schedule_id == sched.id)
    )).scalars().all()
    assert {r.outcome_class for r in rows} == {"transient"}


async def test_trip_broken_holds(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    sched = await _schedule(db_session, seeder)
    for i in range(5):
        await _btask(db_session, exec_settings, sched, kind="broken", artifact_id="art-a",
                     finished_at=NOW - timedelta(minutes=10 - i))
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == [sched.id]
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.enabled is True and sched.breaker_state == "held"
    assert sched.breaker_artifact_id == "art-a" and sched.breaker_retry_at is None
    notes = await _notes(db_session, TYPE_SCHEDULE_BREAKER_HELD)
    assert len(notes) == 1 and notes[0].severity == "error"


async def test_trip_mixed_streak_opens(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    sched = await _schedule(db_session, seeder)
    kinds = ["broken", "broken", "transient", "broken", "broken"]
    for i, kind in enumerate(kinds):
        await _btask(db_session, exec_settings, sched, kind=kind,
                     finished_at=NOW - timedelta(minutes=10 - i))
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == [sched.id]
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open"


async def test_trip_legacy_null_rows_count_as_broken(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    sched = await _schedule(db_session, seeder)
    for i in range(4):  # pre-0016 ledger rows: erroneous, class NULL
        db_session.add(ScheduleOutcomeLedger(
            schedule_id=sched.id, task_id=new_id(), generation=0,
            finished_at=NOW - timedelta(minutes=20 - i), erroneous=True, outcome_class=None,
            recorded_at=NOW - timedelta(minutes=20 - i),
        ))
    await db_session.commit()
    await _btask(db_session, exec_settings, sched, kind="broken", finished_at=NOW)
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == [sched.id]
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 5 and sched.breaker_state == "held"


async def test_trip_success_resets_run_without_tripping(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 5
    sched = await _schedule(db_session, seeder)
    for i in range(4):
        await _btask(db_session, exec_settings, sched, kind="transient",
                     finished_at=NOW - timedelta(minutes=10 - i))
    await _btask(db_session, exec_settings, sched, kind="ok", finished_at=NOW)
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == []
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 0 and sched.breaker_state == "closed"


async def test_trip_threshold_zero_never_trips(db_session, exec_settings, seeder):
    exec_settings.scheduler.auto_disable_after_errors = 0
    sched = await _schedule(db_session, seeder)
    for i in range(6):
        await _btask(db_session, exec_settings, sched, kind="broken",
                     finished_at=NOW - timedelta(minutes=10 - i))
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == []
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.consecutive_error_count == 6 and sched.breaker_state == "closed"


async def test_trip_never_fires_on_old_generation_outcome(db_session, exec_settings, seeder):
    """Review round 01 R-01: a late current-generation success closes the
    breaker while the newest-by-finished_at streak is still >= threshold; an
    old-generation outcome recorded afterwards must not re-trip it."""
    exec_settings.scheduler.auto_disable_after_errors = 5
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, outcome_generation=1)
    for i in range(5):
        await _btask(db_session, exec_settings, sched, kind="broken", generation=1,
                     artifact_id="art-new", finished_at=NOW - timedelta(minutes=10 - i))
    assert await record_task_outcomes(db_session, exec_settings, now=NOW) == [sched.id]
    await db_session.commit()
    # a current-generation success that FINISHED before the streak arrives late
    await _btask(db_session, exec_settings, sched, kind="ok", generation=1,
                 finished_at=NOW - timedelta(minutes=20))
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "closed" and sched.consecutive_error_count == 5
    # an old-generation failure lands now: ledgered, but the breaker stays closed
    await _btask(db_session, exec_settings, sched, kind="broken", generation=0,
                 artifact_id="art-old", finished_at=NOW + timedelta(minutes=2))
    assert await record_task_outcomes(
        db_session, exec_settings, now=NOW + timedelta(minutes=3)
    ) == []
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "closed" and sched.breaker_artifact_id is None
    rows = (await db_session.execute(
        select(ScheduleOutcomeLedger).where(ScheduleOutcomeLedger.schedule_id == sched.id)
    )).scalars().all()
    assert len(rows) == 7 and sum(r.generation == 0 for r in rows) == 1


# =========================================================================== #
# TC-07: the timer gate
# =========================================================================== #


async def _gate_sched(db_session, seeder, **fields) -> Schedule:
    await seeder.healthy_node()
    sched = await _schedule(db_session, seeder)
    fields.setdefault("max_concurrency", 0)
    return await _set(db_session, sched, **fields)


async def test_gate_open_not_due_skips(db_session, exec_settings, seeder, exec_redis,
                                       test_sessionmaker):
    sched = await _gate_sched(db_session, seeder, breaker_state="open",
                              breaker_retry_at=datetime.now(UTC) + timedelta(hours=1))
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    assert await _tasks_of(db_session, sched) == []


async def test_gate_open_due_admits_half_open_probe(db_session, exec_settings, seeder,
                                                    exec_redis, test_sessionmaker):
    sched = await _gate_sched(db_session, seeder, breaker_state="open", outcome_generation=3,
                              breaker_retry_at=datetime.now(UTC) - timedelta(seconds=1))
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is not None
    await _refresh(db_session, sched)
    assert sched.breaker_state == "half_open" and sched.outcome_generation == 4
    assert sched.consecutive_error_count == 0
    assert _close_to(sched.breaker_retry_at, datetime.now(UTC) + timedelta(seconds=7200))
    tasks = await _tasks_of(db_session, sched)
    assert len(tasks) == 1 and tasks[0].schedule_generation == 4


async def test_gate_half_open_before_deadline_skips(db_session, exec_settings, seeder,
                                                    exec_redis, test_sessionmaker):
    sched = await _gate_sched(db_session, seeder, breaker_state="half_open",
                              breaker_retry_at=datetime.now(UTC) + timedelta(hours=1))
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    assert await _tasks_of(db_session, sched) == []


async def test_gate_half_open_past_deadline_reprobes_same_generation(
    db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    sched = await _gate_sched(db_session, seeder, breaker_state="half_open", outcome_generation=4,
                              breaker_retry_at=datetime.now(UTC) - timedelta(seconds=1))
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is not None
    await _refresh(db_session, sched)
    assert sched.breaker_state == "half_open" and sched.outcome_generation == 4
    assert _close_to(sched.breaker_retry_at, datetime.now(UTC) + timedelta(seconds=7200))
    tasks = await _tasks_of(db_session, sched)
    assert [t.schedule_generation for t in tasks] == [4]


async def test_gate_held_skips(db_session, exec_settings, seeder, exec_redis, test_sessionmaker):
    sched = await _gate_sched(db_session, seeder, breaker_state="held")
    template = await db_session.get(ExecutionTemplate, sched.execution_template_id)
    dispatcher = _dispatcher(test_sessionmaker, exec_redis)
    # same artifact as the template -> skip
    await _set(db_session, sched, breaker_artifact_id=template.build_artifact_id)
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    # unknown verdict artifact (NULL) -> skip
    await _set(db_session, sched, breaker_artifact_id=None)
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    assert await _tasks_of(db_session, sched) == []


async def test_gate_concurrency_blocked_stays_open(db_session, exec_settings, seeder,
                                                   exec_redis, test_sessionmaker):
    sched = await _gate_sched(db_session, seeder, breaker_state="open", outcome_generation=2,
                              max_concurrency=1,
                              breaker_retry_at=datetime.now(UTC) - timedelta(seconds=1))
    await _task(db_session, exec_settings, sched, status="running", exec_status="running")
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open" and sched.outcome_generation == 2


@pytest.mark.parametrize("state", ["open", "held"])
async def test_gate_does_not_block_trigger_now(db_session, exec_settings, seeder, exec_redis,
                                               test_sessionmaker, state):
    sched = await _gate_sched(db_session, seeder, breaker_state=state,
                              breaker_retry_at=datetime.now(UTC) + timedelta(hours=1))
    res = await sched_svc.trigger_now(db_session, exec_settings,
                                      _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is not None
    assert len(await _tasks_of(db_session, sched)) == 1
    await _refresh(db_session, sched)
    assert sched.breaker_state == state


# =========================================================================== #
# TC-08: half-open resolution (through the real recorder)
# =========================================================================== #


async def _half_open(db_session, exec_settings, sched) -> int:
    outcomes.enter_half_open(sched, exec_settings.scheduler, NOW)
    await db_session.commit()
    return sched.outcome_generation


async def test_half_open_ok_closes(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW - timedelta(hours=1), breaker_level=2)
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind="ok", generation=gen)
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "closed" and sched.breaker_level == 0
    assert sched.breaker_opened_at is None and sched.breaker_retry_at is None
    assert sched.breaker_reason is None
    notes = await _notes(db_session, TYPE_SCHEDULE_BREAKER_CLOSED)
    assert len(notes) == 1 and notes[0].severity == "info"


async def test_half_open_transient_backoff_sequence(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW)
    expected = [1800, 3600, 7200, 7200]
    for i, seconds in enumerate(expected):
        gen = await _half_open(db_session, exec_settings, sched)
        at = NOW + timedelta(minutes=i + 1)
        await _btask(db_session, exec_settings, sched, kind="transient", generation=gen,
                     finished_at=at)
        await record_task_outcomes(db_session, exec_settings, now=at)
        await db_session.commit()
        await _refresh(db_session, sched)
        assert sched.breaker_state == "open"
        assert _aw(sched.breaker_retry_at) == at + timedelta(seconds=seconds), i


async def test_half_open_broken_holds(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW)
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind="broken", generation=gen)
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "held"
    assert len(await _notes(db_session, TYPE_SCHEDULE_BREAKER_HELD)) == 1


@pytest.mark.parametrize("kind", ["canceled", "no_target"])
async def test_half_open_neutral_retries_at_next_firing(db_session, exec_settings, seeder,
                                                        kind):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW, breaker_level=2)
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind=kind, generation=gen)
    at = NOW + timedelta(minutes=1)
    await record_task_outcomes(db_session, exec_settings, now=at)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open" and sched.breaker_level == 2
    assert _aw(sched.breaker_retry_at) == at


async def test_half_open_old_generation_outcomes_ignored(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW)
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind="broken", generation=gen - 1,
                 finished_at=NOW - timedelta(minutes=2))
    await _btask(db_session, exec_settings, sched, kind="ok", generation=gen - 1,
                 finished_at=NOW - timedelta(minutes=1))
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "half_open"


@pytest.mark.parametrize("state", ["open", "held"])
async def test_half_open_current_ok_closes_open_and_held(db_session, exec_settings, seeder,
                                                         state):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_state=state, breaker_opened_at=NOW,
               breaker_retry_at=NOW + timedelta(hours=1))
    await _btask(db_session, exec_settings, sched, kind="ok")
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "closed"


async def test_half_open_open_ignores_current_errors(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    retry = NOW + timedelta(hours=1)
    await _set(db_session, sched, breaker_state="open", breaker_opened_at=NOW,
               breaker_retry_at=retry, breaker_level=1)
    await _btask(db_session, exec_settings, sched, kind="transient")
    await _btask(db_session, exec_settings, sched, kind="broken",
                 finished_at=NOW + timedelta(seconds=30))
    await record_task_outcomes(db_session, exec_settings, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open" and sched.breaker_level == 1
    assert _aw(sched.breaker_retry_at) == retry


async def test_half_open_late_lost_after_reprobe_still_counts(
    db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    exec_settings.scheduler.lost_outcome_grace_seconds = 3600
    real_now = datetime.now(UTC)
    sched = await _gate_sched(db_session, seeder, breaker_opened_at=real_now)
    outcomes.enter_half_open(sched, exec_settings.scheduler, real_now - timedelta(hours=3))
    await db_session.commit()  # probe deadline (real_now - 1h) already passed
    gen = sched.outcome_generation
    # probe 1: lost 30 min ago, never reclaimed -> waits for the 1h grace
    probe1, _e, _lf = await _btask(db_session, exec_settings, sched, kind="lost",
                                   generation=gen,
                                   finished_at=real_now - timedelta(minutes=30))
    await record_task_outcomes(db_session, exec_settings, now=real_now)
    await db_session.commit()
    await _refresh(db_session, probe1)
    assert probe1.outcome_recorded_at is None
    # the deadline passed: the gate admits probe 2 in the SAME generation
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is not None
    await _refresh(db_session, sched)
    assert sched.outcome_generation == gen and sched.breaker_state == "half_open"
    # probe 1's lost outcome finally lands -> transient -> open, level + 1
    later = real_now + timedelta(hours=2)
    await record_task_outcomes(db_session, exec_settings, now=later)
    await db_session.commit()
    await _refresh(db_session, probe1)
    assert probe1.outcome_recorded_at is not None
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open" and sched.breaker_level == 1
    assert _aw(sched.breaker_retry_at) == later + timedelta(seconds=1800)


async def test_half_open_long_running_success_after_reprobe_closes(
    db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    real_now = datetime.now(UTC)
    sched = await _gate_sched(db_session, seeder, breaker_opened_at=real_now)
    outcomes.enter_half_open(sched, exec_settings.scheduler, real_now - timedelta(hours=3))
    await db_session.commit()
    gen = sched.outcome_generation
    probe1, _e, _lf = await _task(db_session, exec_settings, sched, status="running",
                                  exec_status="running", log_status="active", generation=gen)
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is not None  # max_concurrency=0: probe 2 admitted while probe 1 runs
    await _refresh(db_session, sched)
    assert sched.outcome_generation == gen
    await _finish(db_session, probe1, status="complete", exec_status="finished",
                  error_count=0)
    await record_task_outcomes(db_session, exec_settings,
                               now=datetime.now(UTC) + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "closed"


# =========================================================================== #
# TC-09: escalation
# =========================================================================== #


async def test_escalation_after_24h_on_failed_probe_once(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW - timedelta(hours=25))
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind="transient", generation=gen)
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert _aw(sched.breaker_escalated_at) == NOW
    notes = await _notes(db_session, TYPE_SCHEDULE_BREAKER_OPEN)
    assert len(notes) == 1 and notes[0].severity == "error"
    assert notes[0].payload["escalated"] is True
    # a further failed probe does not escalate again
    gen = await _half_open(db_session, exec_settings, sched)
    later = NOW + timedelta(hours=1)
    await _btask(db_session, exec_settings, sched, kind="transient", generation=gen,
                 finished_at=later)
    await record_task_outcomes(db_session, exec_settings, now=later)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert _aw(sched.breaker_escalated_at) == NOW
    notes = await _notes(db_session, TYPE_SCHEDULE_BREAKER_OPEN)
    assert len(notes) == 1 and notes[0].count == 1


async def test_escalation_not_before_24h(db_session, exec_settings, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW - timedelta(hours=23))
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind="transient", generation=gen)
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_escalated_at is None
    assert await _notes(db_session, TYPE_SCHEDULE_BREAKER_OPEN) == []


async def test_escalation_disabled_when_zero(db_session, exec_settings, seeder):
    exec_settings.scheduler.breaker_escalate_after_seconds = 0
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_opened_at=NOW - timedelta(hours=48))
    gen = await _half_open(db_session, exec_settings, sched)
    await _btask(db_session, exec_settings, sched, kind="transient", generation=gen)
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_escalated_at is None


async def test_escalation_not_on_reprobe_deadline(db_session, exec_settings, seeder, exec_redis,
                                                  test_sessionmaker):
    real_now = datetime.now(UTC)
    sched = await _gate_sched(db_session, seeder,
                              breaker_opened_at=real_now - timedelta(hours=30))
    outcomes.enter_half_open(sched, exec_settings.scheduler, real_now - timedelta(hours=3))
    await db_session.commit()
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is not None
    await _refresh(db_session, sched)
    assert sched.breaker_escalated_at is None
    assert await _notes(db_session, TYPE_SCHEDULE_BREAKER_OPEN) == []


# =========================================================================== #
# TC-10: reset / enable / artifact / view
# =========================================================================== #


@pytest.mark.parametrize("state", ["open", "half_open", "held"])
async def test_reset_endpoint_closes_breaker(exec_client, db_session, seeder, state):
    sched = await _schedule(db_session, seeder, enabled=False)
    await _set(db_session, sched, breaker_state=state, breaker_level=2, outcome_generation=4,
               consecutive_error_count=6, breaker_opened_at=NOW, breaker_artifact_id="x",
               breaker_retry_at=NOW, breaker_reason={"kind": "transient"})
    r = await exec_client.post(f"/api/v1/schedules/{sched.id}/breaker/reset")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["breaker_state"] == "closed" and body["outcome_generation"] == 5
    assert body["consecutive_error_count"] == 0 and body["breaker_level"] == 0
    assert body["breaker_reason"] is None and body["breaker_artifact_id"] is None
    assert body["enabled"] is False  # untouched


async def test_reset_endpoint_closed_is_noop(exec_client, db_session, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, outcome_generation=3, consecutive_error_count=2)
    r = await exec_client.post(f"/api/v1/schedules/{sched.id}/breaker/reset")
    assert r.status_code == 200, r.text
    assert r.json()["outcome_generation"] == 3 and r.json()["consecutive_error_count"] == 2


async def test_reset_endpoint_unknown_schedule_404(exec_client):
    r = await exec_client.post("/api/v1/schedules/nope/breaker/reset")
    assert r.status_code == 404
    assert r.json()["code"] == "schedule.not_found"


async def test_enable_false_to_true_resets_breaker(exec_client, db_session, seeder):
    sched = await _schedule(db_session, seeder, enabled=False)
    await _set(db_session, sched, breaker_state="open", outcome_generation=1,
               breaker_opened_at=NOW, breaker_retry_at=NOW)
    r = await exec_client.put(f"/api/v1/schedules/{sched.id}", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["breaker_state"] == "closed" and r.json()["outcome_generation"] == 2


@pytest.mark.parametrize("state", ["open", "held"])
async def test_enable_true_to_true_keeps_breaker(exec_client, db_session, seeder, state):
    """Declarative sync re-PUTs ``enabled=true`` on every deploy: no effect."""
    sched = await _schedule(db_session, seeder, enabled=True)
    await _set(db_session, sched, breaker_state=state, outcome_generation=1,
               breaker_opened_at=NOW, breaker_retry_at=NOW)
    r = await exec_client.put(f"/api/v1/schedules/{sched.id}",
                              json={"enabled": True, "name": sched.name})
    assert r.status_code == 200, r.text
    assert r.json()["breaker_state"] == state and r.json()["outcome_generation"] == 1


def _tpl(template: ExecutionTemplate) -> dict:
    """Capture the template's PUT body up front (ORM rows expire on rollback)."""
    return {
        "id": template.id, "name": template.name, "command": template.command,
        "node_strategy": template.node_strategy, "node_ids": list(template.node_ids or []),
        "build_artifact_id": template.build_artifact_id,
    }


async def _put_template_artifact(client, tpl: dict, artifact_id: str):
    body = {k: v for k, v in tpl.items() if k != "id"}
    body["build_artifact_id"] = artifact_id
    r = await client.put(f"/api/v1/templates/{tpl['id']}", json=body)
    assert r.status_code == 200, r.text


async def _new_task(session, sched: Schedule, before: set[str]) -> Task:
    """The single task created since ``before`` (SQLite created_at is coarse)."""
    created = [t for t in await _tasks_of(session, sched) if t.id not in before]
    assert len(created) == 1, created
    return created[0]


async def test_held_records_artifact_and_reprobes_new_artifact(
    exec_client, db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    exec_settings.scheduler.auto_disable_after_errors = 3
    sched = await _gate_sched(db_session, seeder)
    tpl = _tpl(await db_session.get(ExecutionTemplate, sched.execution_template_id))
    art_a = tpl["build_artifact_id"]
    for i in range(3):
        await _btask(db_session, exec_settings, sched, kind="broken", artifact_id=art_a,
                     finished_at=NOW - timedelta(minutes=5 - i))
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "held" and sched.breaker_artifact_id == art_a
    gen = sched.outcome_generation
    dispatcher = _dispatcher(test_sessionmaker, exec_redis)
    before = {t.id for t in await _tasks_of(db_session, sched)}
    # same artifact re-PUT (declarative sync with unchanged bytes) -> still skipped
    await _put_template_artifact(exec_client, tpl, art_a)
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    # a new artifact: the template PUT leaves the schedule row alone...
    art_b = (await seeder.build_artifact(sha256="b" * 64)).id
    await _put_template_artifact(exec_client, tpl, art_b)
    await _refresh(db_session, sched)
    assert sched.breaker_state == "held" and sched.breaker_artifact_id == art_a
    # ...and the next timer firing probes it
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is not None
    await _refresh(db_session, sched)
    assert sched.breaker_state == "half_open" and sched.breaker_level == 0
    assert sched.outcome_generation == gen + 1
    probe = await _new_task(db_session, sched, before)
    assert probe.template_snapshot["build_artifact"]["id"] == art_b


async def test_held_artifact_interleave_new_artifact_not_blocked(
    exec_client, db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    sched = await _gate_sched(db_session, seeder)
    tpl = _tpl(await db_session.get(ExecutionTemplate, sched.execution_template_id))
    art_a = tpl["build_artifact_id"]
    await _set(db_session, sched, breaker_state="held", breaker_artifact_id=art_a,
               breaker_opened_at=NOW)
    dispatcher = _dispatcher(test_sessionmaker, exec_redis)
    art_b = (await seeder.build_artifact(sha256="b" * 64)).id
    await _put_template_artifact(exec_client, tpl, art_b)
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is not None
    probe_b = await _new_task(db_session, sched, set())
    assert probe_b.template_snapshot["build_artifact"]["id"] == art_b
    # while B's probe runs, the template moves on to C
    art_c = (await seeder.build_artifact(sha256="c" * 64)).id
    await _put_template_artifact(exec_client, tpl, art_c)
    # B's probe comes back broken -> held on B (not on C)
    await _finish(db_session, probe_b, status="failed", exec_status="failed")
    await record_task_outcomes(db_session, exec_settings,
                               now=datetime.now(UTC) + timedelta(minutes=1))
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "held" and sched.breaker_artifact_id == art_b
    # the next firing probes C
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is not None
    await _refresh(db_session, sched)
    assert sched.breaker_state == "half_open"
    probe_c = await _new_task(db_session, sched, {probe_b.id})
    assert probe_c.template_snapshot["build_artifact"]["id"] == art_c


async def test_held_null_artifact_never_reprobes(
    exec_client, db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    sched = await _gate_sched(db_session, seeder)
    tpl = _tpl(await db_session.get(ExecutionTemplate, sched.execution_template_id))
    await _set(db_session, sched, breaker_state="held", breaker_artifact_id=None)
    art_b = (await seeder.build_artifact(sha256="b" * 64)).id
    await _put_template_artifact(exec_client, tpl, art_b)
    res = await sched_svc.fire_timer(db_session, exec_settings,
                                     _dispatcher(test_sessionmaker, exec_redis), sched)
    assert res is None


async def test_view_exposes_breaker_and_legacy_fields(exec_client, db_session, seeder):
    sched = await _schedule(db_session, seeder)
    await _set(db_session, sched, breaker_state="open", breaker_level=1, breaker_opened_at=NOW,
               breaker_retry_at=NOW + timedelta(minutes=30), breaker_reason={"kind": "transient"})
    r = await exec_client.get("/api/v1/schedules")
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["schedules"] if s["id"] == sched.id)
    for key in ("breaker_state", "breaker_level", "breaker_opened_at", "breaker_retry_at",
                "breaker_escalated_at", "breaker_reason", "breaker_artifact_id",
                "auto_disabled_at", "auto_disabled_reason", "consecutive_error_count"):
        assert key in row, key
    assert row["breaker_state"] == "open" and row["breaker_level"] == 1
    assert row["breaker_reason"] == {"kind": "transient"}


# =========================================================================== #
# TC-20: commit boundaries of the half-open admission
# =========================================================================== #


async def test_boundary_error_before_create_commit_rolls_back(
    db_session, exec_settings, seeder, exec_redis, test_sessionmaker, monkeypatch
):
    sched = await _gate_sched(db_session, seeder, breaker_state="open", outcome_generation=2,
                              breaker_retry_at=datetime.now(UTC) - timedelta(seconds=1))

    async def boom(*_a, **_kw):
        raise RuntimeError("node selection exploded")

    monkeypatch.setattr("dopilot_server.executors.scrapyd.resolve_target_nodes", boom)
    with pytest.raises(RuntimeError):
        await sched_svc.fire_timer(db_session, exec_settings,
                                   _dispatcher(test_sessionmaker, exec_redis), sched)
    await db_session.rollback()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open" and sched.outcome_generation == 2
    assert await _tasks_of(db_session, sched) == []


async def test_boundary_dispatch_unavailable_keeps_single_probe(
    db_session, exec_settings, seeder, exec_redis, test_sessionmaker
):
    sched = await _gate_sched(db_session, seeder, breaker_state="open", outcome_generation=2,
                              breaker_opened_at=datetime.now(UTC),
                              breaker_retry_at=datetime.now(UTC) - timedelta(seconds=1))
    dispatcher = _dispatcher(test_sessionmaker, exec_redis)
    exec_redis.fail_xadd = True
    with pytest.raises(ApiError) as excinfo:
        await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched)
    assert excinfo.value.status_code == 503
    exec_redis.fail_xadd = False
    await _refresh(db_session, sched)
    assert sched.breaker_state == "half_open" and sched.outcome_generation == 3
    tasks = await _tasks_of(db_session, sched)
    assert len(tasks) == 1 and tasks[0].status == "failed"
    execs = (await db_session.execute(
        select(Execution).where(Execution.task_id == tasks[0].id)
    )).scalars().all()
    assert {e.error_code for e in execs} == {"dispatch_unavailable"}
    # an immediate next firing must not admit a second probe
    assert await sched_svc.fire_timer(db_session, exec_settings, dispatcher, sched) is None
    await db_session.rollback()
    await _refresh(db_session, sched)
    assert len(await _tasks_of(db_session, sched)) == 1
    # the recorder classifies the probe as transient (not held)
    later = datetime.now(UTC) + timedelta(minutes=10)
    await record_task_outcomes(db_session, exec_settings, now=later)
    await db_session.commit()
    await _refresh(db_session, sched)
    assert sched.breaker_state == "open" and sched.breaker_level == 1
