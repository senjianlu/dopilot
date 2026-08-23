"""TC-20d / TC-20f: recorder vs consumers under REAL row locks (PostgreSQL only).

These interleavings only exist with ``FOR UPDATE`` semantics, so they run on
``scripts/dev-db.sh`` (``DOPILOT_TEST_DATABASE_URL``) and FAIL — never skip —
without it (see ``pg_sessionmaker`` in conftest).
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import UTC, datetime, timedelta

from dopilot_protocol import AgentEvent, AgentEventType, AgentLogEvent, StopIntent
from dopilot_server.config.settings import RedisSettings
from dopilot_server.models.execution import Execution, ExecutionLogFile, Task
from dopilot_server.models.scheduling import ExecutionTemplate, Schedule
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.redis.reconcile import mark_lost
from dopilot_server.services import executions as svc
from dopilot_server.services import maintenance, outbox, states
from dopilot_server.services.events import apply_event
from dopilot_server.services.executions import new_id
from dopilot_server.services.logs import OUTCOME_SEALED, OUTCOME_TRUNCATED, apply_log_event
from dopilot_server.services.outcomes import record_task_outcomes
from sqlalchemy import select

from .conftest import make_settings


def _settings(tmp_path):
    s = make_settings(logs_root=str(tmp_path / "logs"), artifacts_root=str(tmp_path / "art"))
    s.scheduler.auto_disable_after_errors = 100
    s.logs.max_file_bytes = 1024
    s.logs.log_drain_timeout_seconds = 300
    return s


async def _seed(maker, settings, *, status, exec_status, log_status, finished_at, source):
    async with maker() as s:
        tpl = ExecutionTemplate(id=new_id(), name=f"tpl-{uuid.uuid4().hex[:8]}",
                                node_strategy="all", node_ids=[])
        s.add(tpl)
        await s.flush()
        sched = Schedule(id=new_id(), name=f"sch-{uuid.uuid4().hex[:8]}",
                         execution_template_id=tpl.id, trigger_type="interval",
                         interval_seconds=30, enabled=True)
        s.add(sched)
        await s.flush()
        task = Task(id=new_id(), artifact_type="scrapy", target="demo:phase1", status=status,
                    params={}, source=source, schedule_id=sched.id, schedule_generation=0,
                    finished_at=finished_at, created_at=finished_at - timedelta(minutes=1)
                    if finished_at else datetime.now(UTC))
        s.add(task)
        await s.flush()  # FK order: task before execution (no ORM relationship)
        execution = Execution(id=new_id(), task_id=task.id, agent_id="agent-1",
                              status=exec_status, error_detail={}, finished_at=finished_at)
        s.add(execution)
        lf = svc.create_log_file(s, settings, task, execution)
        lf.status = log_status
        await s.commit()
        return sched.id, task.id, execution.id


def _log_event(task_id, execution_id, content: bytes) -> AgentLogEvent:
    return AgentLogEvent(agent_id="agent-1", task_id=task_id, execution_id=execution_id,
                         offset=0, content_b64=base64.b64encode(content).decode(),
                         size_bytes=len(content), created_at="t")


def _finished_event(task_id, execution_id) -> AgentEvent:
    return AgentEvent(event_id=new_id(), agent_id="agent-1", task_id=task_id,
                      execution_id=execution_id, type=AgentEventType.finished,
                      error_count=0, finish_reason="finished", created_at="t")


async def _task_row(maker, task_id) -> Task:
    async with maker() as s:
        return (await s.execute(select(Task).where(Task.id == task_id))).scalar_one()


async def _schedule_row(maker, sched_id) -> Schedule:
    async with maker() as s:
        return (await s.execute(select(Schedule).where(Schedule.id == sched_id))).scalar_one()


async def _lf_row(maker, task_id, execution_id) -> ExecutionLogFile:
    async with maker() as s:
        return (await s.execute(select(ExecutionLogFile).where(
            ExecutionLogFile.task_id == task_id, ExecutionLogFile.execution_id == execution_id,
        ))).scalar_one()


# --- TC-20d (a): consumer holds the log-file lock past a truncation; recorder waits ------


async def test_recorder_waits_for_uncommitted_truncation(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    sched_id, task_id, exec_id = await _seed(
        pg_sessionmaker, settings, status="complete", exec_status="finished",
        log_status="active", finished_at=now - timedelta(seconds=400),
        source=states.TASK_SOURCE_TIMER,
    )
    wrote = asyncio.Event()
    release = asyncio.Event()
    loop = asyncio.get_running_loop()
    t_commit = {"at": None}

    async def consumer() -> None:
        async with pg_sessionmaker() as s:
            out = await apply_log_event(s, settings, _log_event(task_id, exec_id, b"x" * 2048))
            assert out == OUTCOME_TRUNCATED
            wrote.set()
            await release.wait()
            t_commit["at"] = loop.time()
            await s.commit()

    async def recorder() -> float:
        async with pg_sessionmaker() as s:
            await record_task_outcomes(s, settings, now=now)
            await s.commit()
        return loop.time()

    c = asyncio.create_task(consumer())
    await wrote.wait()
    r = asyncio.create_task(recorder())
    await asyncio.sleep(0.3)
    assert not r.done()  # blocked on the log-file row lock
    release.set()
    await c
    r_done = await r
    assert r_done >= t_commit["at"]
    task = await _task_row(pg_sessionmaker, task_id)
    assert task.outcome_recorded_at is not None and task.outcome_erroneous is True
    sched = await _schedule_row(pg_sessionmaker, sched_id)
    assert sched.consecutive_error_count == 1


# --- TC-20d (b): recorder sealed first; a late increment is dropped ----------------------


async def test_late_increment_after_seal_is_dropped(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    sched_id, task_id, exec_id = await _seed(
        pg_sessionmaker, settings, status="complete", exec_status="finished",
        log_status="active", finished_at=now - timedelta(seconds=400),
        source=states.TASK_SOURCE_TIMER,
    )
    async with pg_sessionmaker() as s:
        await record_task_outcomes(s, settings, now=now)
        await s.commit()
    async with pg_sessionmaker() as s:
        out = await apply_log_event(s, settings, _log_event(task_id, exec_id, b"x" * 2048))
        await s.commit()
    assert out == OUTCOME_SEALED
    lf = await _lf_row(pg_sessionmaker, task_id, exec_id)
    assert lf.status == "complete" and lf.log_integrity == "complete" and lf.size_bytes == 0
    task = await _task_row(pg_sessionmaker, task_id)
    assert task.outcome_erroneous is False
    assert (await _schedule_row(pg_sessionmaker, sched_id)).consecutive_error_count == 0


# --- TC-20d (c): recorder records lost; event override waits, then clears the stamp ------


async def test_override_after_recorded_lost_triggers_rejudge(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    sched_id, task_id, exec_id = await _seed(
        pg_sessionmaker, settings, status="lost", exec_status="lost",
        log_status="finalizing", finished_at=now - timedelta(hours=1),
        source=states.TASK_SOURCE_TIMER,
    )
    async with pg_sessionmaker() as s:
        outbox.create_stop_outbox(s, task_id=task_id, execution_id=exec_id, agent_id="agent-1",
                                  intent=StopIntent.reclaim)
        await s.commit()
    recorded = asyncio.Event()
    release = asyncio.Event()

    async def recorder() -> None:
        async with pg_sessionmaker() as s:
            await record_task_outcomes(s, settings, now=now)
            recorded.set()
            await release.wait()
            await s.commit()

    async def event() -> str:
        async with pg_sessionmaker() as s:
            out = await apply_event(s, _finished_event(task_id, exec_id), "msg-override")
            await s.commit()
            return out

    r = asyncio.create_task(recorder())
    await recorded.wait()
    e = asyncio.create_task(event())
    await asyncio.sleep(0.3)
    assert not e.done()  # blocked on the task row lock held by the recorder
    release.set()
    await r
    assert await e == "override_lost"
    task = await _task_row(pg_sessionmaker, task_id)
    assert task.status == "complete" and task.outcome_recorded_at is None
    assert (await _schedule_row(pg_sessionmaker, sched_id)).consecutive_error_count == 1
    async with pg_sessionmaker() as s:
        await record_task_outcomes(s, settings, now=now + timedelta(hours=1))
        await s.commit()
    task = await _task_row(pg_sessionmaker, task_id)
    assert task.outcome_erroneous is False
    assert (await _schedule_row(pg_sessionmaker, sched_id)).consecutive_error_count == 0


# --- TC-20d (d): event holds the task lock first; recorder waits and records finished ----


async def test_recorder_waits_for_uncommitted_override(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    sched_id, task_id, exec_id = await _seed(
        pg_sessionmaker, settings, status="lost", exec_status="lost",
        log_status="complete", finished_at=now - timedelta(days=2),
        source=states.TASK_SOURCE_TIMER,
    )
    applied = asyncio.Event()
    release = asyncio.Event()

    async def event() -> None:
        async with pg_sessionmaker() as s:
            await apply_event(s, _finished_event(task_id, exec_id), "msg-first")
            applied.set()
            await release.wait()
            await s.commit()

    async def recorder() -> None:
        async with pg_sessionmaker() as s:
            await record_task_outcomes(s, settings, now=now)
            await s.commit()

    e = asyncio.create_task(event())
    await applied.wait()
    r = asyncio.create_task(recorder())
    await asyncio.sleep(0.3)
    assert not r.done()
    release.set()
    await asyncio.gather(e, r)
    task = await _task_row(pg_sessionmaker, task_id)
    assert task.status == "complete" and task.outcome_erroneous is False
    assert (await _schedule_row(pg_sessionmaker, sched_id)).consecutive_error_count == 0


# --- TC-20f: stale terminal writers never overwrite a committed finished ----------------


async def test_stale_mark_lost_and_dispatch_timeout_lose_to_finished(
    pg_sessionmaker, tmp_path, fake_redis
):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    for writer in ("mark_lost", "dispatch_timeout", "mark_task_lost"):
        _sched_id, task_id, exec_id = await _seed(
            pg_sessionmaker, settings, status="running", exec_status="running",
            log_status="active", finished_at=None, source=states.TASK_SOURCE_TIMER,
        )
        async with pg_sessionmaker() as stale:
            # reconcile selects its candidates WITHOUT a lock
            execution = (await stale.execute(
                select(Execution).where(Execution.id == exec_id)
            )).scalar_one()
            task = (await stale.execute(select(Task).where(Task.id == task_id))).scalar_one()
            if writer == "dispatch_timeout":
                row = outbox.create_run_outbox(stale, task_id=task_id, execution_id=exec_id,
                                               agent_id="agent-1", payload={}, manual=True)
                await stale.commit()
            # meanwhile the agent's finished commits
            async with pg_sessionmaker() as other:
                out = await apply_event(other, _finished_event(task_id, exec_id), f"m-{writer}")
                assert out == "applied"
                await other.commit()
            if writer == "mark_lost":
                assert await mark_lost(stale, execution, "heartbeat_timeout", now) is False
            elif writer == "dispatch_timeout":
                dispatcher = CommandDispatcher(
                    pg_sessionmaker, CommandProducer(fake_redis(), RedisSettings())
                )
                await dispatcher._fail_execution_dispatch_timeout(stale, row)
            else:
                import pytest
                from dopilot_server.errors import ApiError

                with pytest.raises(ApiError):
                    await maintenance.mark_task_lost(stale, task)
            await stale.commit()
        final_task = await _task_row(pg_sessionmaker, task_id)
        async with pg_sessionmaker() as s:
            final_exec = (await s.execute(
                select(Execution).where(Execution.id == exec_id)
            )).scalar_one()
        assert final_task.status == "complete", writer
        assert final_exec.status == "finished", writer
