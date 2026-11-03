"""Schedule circuit breaker under REAL row locks (PostgreSQL only; decision 0025).

SQLite compiles ``FOR UPDATE`` away, so the serializations below are only
observable on PostgreSQL. Fails (never skips) without
``DOPILOT_TEST_DATABASE_URL`` — see the ``pg_sessionmaker`` fixture. Everything
is seeded INSIDE PostgreSQL (the shared ``seeder`` fixture is SQLite-bound).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from dopilot_server.models.execution import Execution, Task
from dopilot_server.models.scheduling import ExecutionTemplate, Schedule, ScheduleOutcomeLedger
from dopilot_server.services import executions as exec_svc
from dopilot_server.services import outcomes, templates
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services.executions import new_id
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from .conftest import Seeder
from .test_schedule_concurrency_pg import _dispatcher, _seed_scheduling, _settings, _task_count

BLOCK_PROBE_SECONDS = 0.3
DONE_TIMEOUT = 10


async def _get(maker, schedule_id: str) -> Schedule:
    async with maker() as session:
        return await sched_svc.get_schedule_or_404(session, schedule_id)


async def _update(maker, schedule_id: str, **fields) -> None:
    async with maker() as session:
        row = await sched_svc.get_schedule_or_404(session, schedule_id)
        for key, value in fields.items():
            setattr(row, key, value)
        await session.commit()


async def _seed_failed_tasks(maker, settings, schedule_id: str, *, n: int, artifact_id: str,
                             kind: str = "broken") -> None:
    """``n`` recorded-ready failures (generation 0) whose snapshot names ``artifact_id``."""
    now = datetime.now(UTC)
    async with maker() as session:
        for i in range(n):
            finished = now - timedelta(minutes=10 - i)
            task = Task(
                id=new_id(), artifact_type="scrapy", target="demo:phase1",
                status="complete" if kind == "transient" else "failed", params={},
                source="schedule_timer", schedule_id=schedule_id, schedule_generation=0,
                template_snapshot={"build_artifact": {"id": artifact_id}},
                finished_at=finished, created_at=finished - timedelta(minutes=1),
            )
            session.add(task)
            await session.flush()  # no ORM relationship: insert the task first
            execution = Execution(
                id=new_id(), task_id=task.id, agent_id="agent-1",
                status="finished" if kind == "transient" else "failed", error_detail={},
                error_count=2 if kind == "transient" else None,
                finish_reason="finished" if kind == "transient" else None,
                outcome_class="transient" if kind == "transient" else None,
                finished_at=finished,
            )
            session.add(execution)
            lf = exec_svc.create_log_file(session, settings, task, execution)
            lf.status = "complete"
            lf.finished_at = finished
        await session.commit()


async def _template_artifact(maker, template_id: str) -> str:
    async with maker() as session:
        return (await session.get(ExecutionTemplate, template_id)).build_artifact_id


async def _put_template(maker, settings, template_id: str, artifact_id: str) -> None:
    async with maker() as session:
        template = await templates.get_template_or_404(session, template_id)
        await templates.update_template(session, template, {"build_artifact_id": artifact_id})
        await session.commit()


async def _new_artifact(maker, settings, sha: str) -> str:
    async with maker() as session:
        artifact = await Seeder(session, settings).build_artifact(sha256=sha * 64)
        await session.commit()
        return artifact.id


async def _fire(maker, settings, dispatcher, schedule_id: str):
    async with maker() as session:
        row = await sched_svc.get_schedule_or_404(session, schedule_id)
        return await sched_svc.fire_timer(session, settings, dispatcher, row)


# --- two concurrent timer firings on a due open breaker -> one probe ----------


async def test_concurrent_due_firings_admit_one_probe(pg_sessionmaker, exec_redis, tmp_path):
    settings = _settings(tmp_path)
    _tpl, sid = await _seed_scheduling(pg_sessionmaker, settings, max_concurrency=0,
                                       enabled=True)
    await _update(pg_sessionmaker, sid, breaker_state="open", outcome_generation=1,
                  breaker_retry_at=datetime.now(UTC) - timedelta(seconds=1))
    dispatcher = _dispatcher(pg_sessionmaker, exec_redis)
    results = await asyncio.gather(
        _fire(pg_sessionmaker, settings, dispatcher, sid),
        _fire(pg_sessionmaker, settings, dispatcher, sid),
    )
    assert sum(r is not None for r in results) == 1, results
    assert await _task_count(pg_sessionmaker, sid) == 1
    row = await _get(pg_sessionmaker, sid)
    assert row.breaker_state == "half_open" and row.outcome_generation == 2


# --- re-enable / reset serialize on the row lock ----------------------------------


async def _holding_then(maker, first, second_coro_factory):
    """Run ``first(session)`` holding its row lock uncommitted, start the second
    operation (it must block), then commit the first and let the second finish."""
    async with maker() as session_a:
        await first(session_a)
        task_b = asyncio.create_task(second_coro_factory())
        await asyncio.sleep(BLOCK_PROBE_SECONDS)
        assert not task_b.done(), "the second operation must wait for the row lock"
        await session_a.commit()
    await asyncio.wait_for(task_b, DONE_TIMEOUT)


def _enable(maker, sid):
    async def run():
        async with maker() as session:
            row = await sched_svc.get_schedule_or_404(session, sid)
            await sched_svc.update_schedule(session, row, {"enabled": True})
            await session.commit()
    return run


def _reset(maker, sid):
    async def run():
        async with maker() as session:
            await sched_svc.reset_schedule_breaker(session, sid)
            await session.commit()
    return run


async def test_concurrent_enables_reset_once(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    _tpl, sid = await _seed_scheduling(pg_sessionmaker, settings, max_concurrency=1,
                                       enabled=False)

    async def first(session):
        row = await sched_svc.get_schedule_or_404(session, sid)
        await sched_svc.update_schedule(session, row, {"enabled": True})

    await _holding_then(pg_sessionmaker, first, _enable(pg_sessionmaker, sid))
    row = await _get(pg_sessionmaker, sid)
    assert row.enabled is True and row.outcome_generation == 1


async def test_reset_then_enable_bumps_twice(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    _tpl, sid = await _seed_scheduling(pg_sessionmaker, settings, max_concurrency=1,
                                       enabled=False)
    await _update(pg_sessionmaker, sid, breaker_state="open", breaker_retry_at=datetime.now(UTC))

    async def first(session):
        await sched_svc.reset_schedule_breaker(session, sid)

    await _holding_then(pg_sessionmaker, first, _enable(pg_sessionmaker, sid))
    row = await _get(pg_sessionmaker, sid)
    assert row.outcome_generation == 2
    assert row.breaker_state == "closed" and row.enabled is True


async def test_enable_then_reset_bumps_once(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    _tpl, sid = await _seed_scheduling(pg_sessionmaker, settings, max_concurrency=1,
                                       enabled=False)
    await _update(pg_sessionmaker, sid, breaker_state="open", breaker_retry_at=datetime.now(UTC))

    async def first(session):
        row = await sched_svc.get_schedule_or_404(session, sid)
        await sched_svc.update_schedule(session, row, {"enabled": True})

    await _holding_then(pg_sessionmaker, first, _reset(pg_sessionmaker, sid))
    row = await _get(pg_sessionmaker, sid)
    assert row.outcome_generation == 1  # the reset saw ``closed`` and did nothing
    assert row.breaker_state == "closed" and row.enabled is True


# --- held(B) vs a template change to C: either commit order -> C is probed ------


async def _held_vs_template(maker, settings, exec_redis, *, template_first: bool) -> None:
    settings.scheduler.auto_disable_after_errors = 3
    tpl_id, sid = await _seed_scheduling(maker, settings, max_concurrency=0, enabled=True)
    art_b = await _template_artifact(maker, tpl_id)
    await _seed_failed_tasks(maker, settings, sid, n=3, artifact_id=art_b)
    art_c = await _new_artifact(maker, settings, "c")
    async with maker() as recorder:
        await outcomes.record_task_outcomes(recorder, settings)
        if template_first:
            # the recorder holds the schedule row; the template change must not wait
            await asyncio.wait_for(_put_template(maker, settings, tpl_id, art_c), DONE_TIMEOUT)
        await recorder.commit()
    if not template_first:
        await _put_template(maker, settings, tpl_id, art_c)
    row = await _get(maker, sid)
    assert row.breaker_state == "held" and row.breaker_artifact_id == art_b
    dispatcher = _dispatcher(maker, exec_redis)
    assert await _fire(maker, settings, dispatcher, sid) is not None
    row = await _get(maker, sid)
    assert row.breaker_state == "half_open"
    async with maker() as session:
        probe = (await session.execute(
            select(Task).where(Task.schedule_id == sid, Task.status != "failed")
        )).scalar_one()
    assert probe.template_snapshot["build_artifact"]["id"] == art_c


async def test_held_vs_template_change_template_commits_first(pg_sessionmaker, exec_redis,
                                                              tmp_path):
    await _held_vs_template(pg_sessionmaker, _settings(tmp_path), exec_redis,
                            template_first=True)


async def test_held_vs_template_change_recorder_commits_first(pg_sessionmaker, exec_redis,
                                                              tmp_path):
    await _held_vs_template(pg_sessionmaker, _settings(tmp_path), exec_redis,
                            template_first=False)


# --- recorder holding two schedules of one template vs a template update --------


async def test_recorder_and_template_update_do_not_deadlock(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    settings.scheduler.auto_disable_after_errors = 3
    tpl_id, sid1 = await _seed_scheduling(pg_sessionmaker, settings, max_concurrency=0,
                                          enabled=True)
    async with pg_sessionmaker() as session:
        sched2 = await sched_svc.create_schedule(session, {
            "name": "pg-conc-schedule-2", "execution_template_id": tpl_id,
            "trigger_type": "interval", "interval_seconds": 30, "enabled": True,
        })
        await session.commit()
        sid2 = sched2.id
    art = await _template_artifact(pg_sessionmaker, tpl_id)
    await _seed_failed_tasks(pg_sessionmaker, settings, sid1, n=3, artifact_id=art)
    await _seed_failed_tasks(pg_sessionmaker, settings, sid2, n=3, artifact_id=art)
    art_new = await _new_artifact(pg_sessionmaker, settings, "d")

    async with pg_sessionmaker() as recorder:
        tripped = await outcomes.record_task_outcomes(recorder, settings)
        assert sorted(tripped) == sorted([sid1, sid2])
        # The recorder transaction is still open and holds BOTH schedule rows.
        async with pg_sessionmaker() as probe:
            for sid in (sid1, sid2):
                try:
                    await probe.execute(
                        text("SELECT id FROM schedules WHERE id = :id FOR UPDATE NOWAIT"),
                        {"id": sid},
                    )
                    raise AssertionError(f"schedule {sid} is not locked by the recorder")
                except DBAPIError as exc:
                    assert "could not obtain lock" in str(exc.orig), exc
                    await probe.rollback()
        # While those locks are held, a template update commits without waiting.
        await asyncio.wait_for(
            _put_template(pg_sessionmaker, settings, tpl_id, art_new), DONE_TIMEOUT
        )
        assert await _template_artifact(pg_sessionmaker, tpl_id) == art_new
        await recorder.commit()
    for sid in (sid1, sid2):
        assert (await _get(pg_sessionmaker, sid)).breaker_state == "held"


# --- a failing notification write cannot abort the outcome transaction ----------


async def test_notification_failure_does_not_abort_recording(pg_sessionmaker, tmp_path,
                                                             monkeypatch):
    settings = _settings(tmp_path)
    settings.scheduler.auto_disable_after_errors = 3
    tpl_id, sid = await _seed_scheduling(pg_sessionmaker, settings, max_concurrency=0,
                                         enabled=True)
    art = await _template_artifact(pg_sessionmaker, tpl_id)
    await _seed_failed_tasks(pg_sessionmaker, settings, sid, n=3, artifact_id=art,
                             kind="transient")
    calls: list[str] = []

    async def failing_notify(session, **kwargs):
        calls.append(kwargs["type"])
        await session.execute(text("SELECT 1/0"))  # aborts the txn without a savepoint
        raise AssertionError("unreachable")

    monkeypatch.setattr(outcomes.notif, "notify", failing_notify)
    async with pg_sessionmaker() as session:
        tripped = await outcomes.record_task_outcomes(session, settings)
        await session.commit()
    assert tripped == [sid] and calls == ["schedule_breaker_open"]
    async with pg_sessionmaker() as session:
        unrecorded = (await session.execute(
            select(func.count()).select_from(Task).where(
                Task.schedule_id == sid, Task.outcome_recorded_at.is_(None)
            )
        )).scalar_one()
        ledger = (await session.execute(
            select(func.count()).select_from(ScheduleOutcomeLedger).where(
                ScheduleOutcomeLedger.schedule_id == sid
            )
        )).scalar_one()
        row = await sched_svc.get_schedule_or_404(session, sid)
    assert unrecorded == 0 and ledger == 3
    assert row.breaker_state == "open" and row.breaker_retry_at is not None
