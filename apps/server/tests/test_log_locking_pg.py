"""TC-13b / TC-13c: LogConsumer vs retention under REAL row locks (PostgreSQL only).

Fails (never skips) without ``DOPILOT_TEST_DATABASE_URL`` — see ``pg_sessionmaker``.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dopilot_protocol import AgentLogEvent
from dopilot_server.logs.dir_gauge import LogsDirGauge
from dopilot_server.models.execution import Execution, ExecutionLogFile, Task
from dopilot_server.services import executions as svc
from dopilot_server.services import maintenance as maint
from dopilot_server.services import states
from dopilot_server.services.executions import new_id
from dopilot_server.services.logs import OUTCOME_SEALED, apply_log_event
from dopilot_server.services.outcomes import record_task_outcomes
from sqlalchemy import select

from .conftest import make_settings


def _settings(tmp_path):
    s = make_settings(logs_root=str(tmp_path / "logs"), artifacts_root=str(tmp_path / "art"))
    s.logs.max_file_bytes = 2048
    s.logs.max_total_bytes = 0
    s.logs.log_drain_timeout_seconds = 300
    s.logs.retention_days = 1
    return s


async def _seed(maker, settings, *, finished_at, log_status="active", size=0):
    async with maker() as s:
        task = Task(id=new_id(), artifact_type="scrapy", target="x", status=states.TASK_COMPLETE,
                    params={}, finished_at=finished_at, created_at=finished_at)
        s.add(task)
        await s.flush()
        execution = Execution(id=new_id(), task_id=task.id, agent_id="agent-1",
                              status=states.EXEC_FINISHED, error_detail={},
                              finished_at=finished_at)
        s.add(execution)
        lf = svc.create_log_file(s, settings, task, execution)
        lf.status = log_status
        lf.size_bytes = size
        lf.final_offset = size if log_status == "complete" else None
        await s.commit()
        path = lf.storage_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"z" * size)
    return task.id, execution.id, path


def _event(task_id, execution_id, offset, content: bytes) -> AgentLogEvent:
    return AgentLogEvent(agent_id="agent-1", task_id=task_id, execution_id=execution_id,
                         offset=offset, content_b64=base64.b64encode(content).decode(),
                         size_bytes=len(content), created_at="t")


async def _lf(maker, task_id, execution_id) -> ExecutionLogFile:
    async with maker() as s:
        return (await s.execute(select(ExecutionLogFile).where(
            ExecutionLogFile.task_id == task_id, ExecutionLogFile.execution_id == execution_id,
        ))).scalar_one()


# --- TC-13b: consumer holds the row; truncate/evict wait, then skip the unsealed file --


async def test_maintenance_waits_for_consumer_then_skips_unsealed(pg_sessionmaker, tmp_path):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    gauge = LogsDirGauge(settings.logs.root_dir, budget=0)
    loop = asyncio.get_running_loop()

    async def hold_row_then(task_id, exec_id, content, wrote, release, t_commit):
        """A LogConsumer apply that pauses with the row lock held, then commits."""
        async with pg_sessionmaker() as s:
            out = await apply_log_event(
                s, settings, _event(task_id, exec_id, 0, content), gauge=gauge
            )
            wrote.set()
            await release.wait()
            t_commit["at"] = loop.time()
            await s.commit()
            return out

    async def maintenance() -> tuple[float, int, dict]:
        async with pg_sessionmaker() as s:
            cut = await maint.truncate_oversized_log_files(s, settings, gauge=gauge)
            await s.commit()
            evicted = await maint.evict_logs_dir_to_budget(
                s, settings, gauge=LogsDirGauge(settings.logs.root_dir, budget=1), now=now
            )
        return loop.time(), cut, evicted

    # Phase 1: an oversized but still-ACTIVE (draining) log is never a candidate —
    # maintenance skips it by eligibility, so no lock is even attempted.
    task_id, exec_id, path = await _seed(
        pg_sessionmaker, settings, finished_at=now - timedelta(seconds=10), size=5000,
    )
    await gauge.calibrate()
    wrote, release, t_commit = asyncio.Event(), asyncio.Event(), {"at": 0.0}
    c = asyncio.create_task(hold_row_then(task_id, exec_id, b"a" * 100, wrote, release, t_commit))
    await wrote.wait()
    try:
        m = asyncio.create_task(maintenance())
        await asyncio.sleep(0.3)
        assert m.done()
        _t, cut, evicted = await m
        assert cut == 0 and evicted["evicted"] == 0
    finally:
        release.set()
    # the 5000-byte file is already past the 2048 cap: the consumer writes only
    # the size-cap marker (its own truncation), the file stays ACTIVE
    assert await c == "truncated"
    lf = await _lf(pg_sessionmaker, task_id, exec_id)
    assert lf.status == "active" and Path(path).stat().st_size == lf.size_bytes > 5000

    # Phase 2: the file is SEALED (a candidate) while a consumer still holds its
    # row lock mid-transaction -> maintenance must block until that commit.
    settings.logs.max_total_bytes = 1
    async with pg_sessionmaker() as s:
        await record_task_outcomes(s, settings, now=now + timedelta(seconds=400))
        await s.commit()
    lf = await _lf(pg_sessionmaker, task_id, exec_id)
    assert lf.status == "complete"
    wrote, release, t_commit = asyncio.Event(), asyncio.Event(), {"at": 0.0}
    c = asyncio.create_task(hold_row_then(task_id, exec_id, b"late" * 10, wrote, release, t_commit))
    await wrote.wait()
    try:
        m = asyncio.create_task(maintenance())
        await asyncio.sleep(0.3)
        assert not m.done()  # blocked behind the consumer's row lock
    finally:
        release.set()
    assert await c == OUTCOME_SEALED
    done_at, cut, evicted = await m
    assert done_at >= t_commit["at"]
    assert cut == 1  # re-read under the lock: sealed + oversized -> truncated
    assert evicted["evicted"] == 1  # then evicted down to the 1-byte budget
    assert not Path(path).exists()
    async with pg_sessionmaker() as s:
        gone = (await s.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        assert gone is None


# --- TC-13c: expired row committed, unlink pending -> late increment writes nothing ---------


async def test_expired_row_rejects_late_increment_no_orphan(
    pg_sessionmaker, tmp_path, monkeypatch
):
    settings = _settings(tmp_path)
    now = datetime.now(UTC)
    task_id, exec_id, path = await _seed(
        pg_sessionmaker, settings, finished_at=now - timedelta(days=3),
        log_status="complete", size=100,
    )
    gauge = LogsDirGauge(settings.logs.root_dir, budget=0)
    await gauge.calibrate()
    expired = asyncio.Event()
    release = asyncio.Event()
    from dopilot_server.logs import files as files_mod

    real_aremove = files_mod.aremove

    async def paused_aremove(p):
        expired.set()  # STEP 1 (expired) is committed by now
        await release.wait()
        return await real_aremove(p)

    monkeypatch.setattr(files_mod, "aremove", paused_aremove)

    async def cleanup() -> None:
        async with pg_sessionmaker() as s:
            await maint.cleanup_terminal_data(s, settings, cutoff=now, gauge=gauge)

    c = asyncio.create_task(cleanup())
    await expired.wait()
    try:
        async with pg_sessionmaker() as s:
            out = await apply_log_event(
                s, settings, _event(task_id, exec_id, 100, b"late" * 100), gauge=gauge
            )
            await s.commit()
        assert out == OUTCOME_SEALED
        assert Path(path).stat().st_size == 100  # nothing appended
    finally:
        release.set()
    await c
    assert not Path(path).exists()
    async with pg_sessionmaker() as s:
        assert (await s.execute(select(ExecutionLogFile).where(
            ExecutionLogFile.task_id == task_id
        ))).scalar_one_or_none() is None
    # no orphan file was recreated after the unlink either
    async with pg_sessionmaker() as s:
        out = await apply_log_event(
            s, settings, _event(task_id, exec_id, 500, b"x" * 10), gauge=gauge
        )
    assert out == "no_log_file" and not Path(path).exists()
    assert gauge.value == 0
