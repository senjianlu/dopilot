"""Log-flood guard retention steps: TC-13 / TC-14 / TC-15 / TC-16 / TC-27 / TC-32."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dopilot_protocol import LOG_STREAM, command_stream
from dopilot_server.logs.dir_gauge import LogsDirGauge, walk_size
from dopilot_server.models.command_outbox import CommandOutbox
from dopilot_server.models.execution import Execution, Task
from dopilot_server.models.node import Node
from dopilot_server.models.notification import (
    TYPE_LOGS_DIR_OVER_BUDGET,
    TYPE_STALE_COMMAND_STREAMS_DELETED,
    Notification,
)
from dopilot_server.resource_stats import collect_snapshot
from dopilot_server.services import executions as svc
from dopilot_server.services import maintenance as maint
from dopilot_server.services import states
from dopilot_server.services.executions import new_id
from sqlalchemy import select

from .conftest import make_settings

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


async def _seed(
    session, settings, *, size: int, log_status: str = "complete",
    task_status: str = states.TASK_COMPLETE, finished_at: datetime | None = None,
    agent_id: str = "agent-1", exec_status: str | None = None,
):
    finished_at = finished_at or NOW - timedelta(days=1)
    task = Task(id=new_id(), artifact_type="scrapy", target="demo:x", status=task_status,
                params={}, finished_at=finished_at if task_status in states.TASK_TERMINAL else None)
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id=agent_id,
        status=exec_status or (states.EXEC_FINISHED if task_status in states.TASK_TERMINAL
                               else states.EXEC_RUNNING),
        error_detail={},
    )
    session.add(execution)
    lf = svc.create_log_file(session, settings, task, execution)
    lf.status = log_status
    lf.size_bytes = size
    lf.final_offset = size if log_status == "complete" else None
    await session.commit()
    Path(lf.storage_path).parent.mkdir(parents=True, exist_ok=True)
    Path(lf.storage_path).write_bytes(b"z" * size)
    return task, execution, lf


async def _notes(session, type_):
    return list((await session.execute(
        select(Notification).where(Notification.type == type_)
    )).scalars().all())


# --- TC-13: truncate only sealed oversized files ----------------------------------------


async def test_truncate_oversized_only_sealed(db_session, exec_settings):
    exec_settings.logs.max_file_bytes = 2048
    root = Path(exec_settings.logs.root_dir)
    gauge = LogsDirGauge(root, budget=0)
    _t1, _e1, sealed_big = await _seed(db_session, exec_settings, size=5000)
    _t2, _e2, sealed_small = await _seed(db_session, exec_settings, size=1000)
    _t3, _e3, draining = await _seed(db_session, exec_settings, size=5000, log_status="active")
    _t4, _e4, active = await _seed(db_session, exec_settings, size=5000, log_status="active",
                                   task_status=states.TASK_RUNNING)
    await gauge.calibrate()
    before = gauge.value
    cut = await maint.truncate_oversized_log_files(db_session, exec_settings, gauge=gauge)
    await db_session.commit()
    assert cut == 1
    marker = b"\n[dopilot:log-truncated max_bytes=2048 reason=maintenance]\n"
    body = Path(sealed_big.storage_path).read_bytes()
    assert body == b"z" * 2048 + marker
    await db_session.refresh(sealed_big)
    assert sealed_big.log_integrity == "truncated"
    assert sealed_big.truncation_reason == "maintenance"
    assert sealed_big.size_bytes == len(body) == sealed_big.final_offset
    assert gauge.value == before - (5000 - len(body)) == walk_size(root)
    for lf in (sealed_small, draining, active):
        assert Path(lf.storage_path).stat().st_size == lf.size_bytes
        await db_session.refresh(lf)
        assert lf.log_integrity == "complete"
    # cap 0 -> nothing
    exec_settings.logs.max_file_bytes = 0
    assert await maint.truncate_oversized_log_files(db_session, exec_settings, gauge=gauge) == 0


async def test_truncate_boundary_cap_plus_one_and_idempotent_marker_state(
    db_session, exec_settings
):
    """R-03 (round 4): the candidate threshold is ``size > cap`` — a raw ``cap+1``
    sealed file with no marker IS cut; a file already in the ``cap + marker``
    state (any dopilot marker, integrity already 'truncated') is left alone."""
    cap = 2048
    exec_settings.logs.max_file_bytes = cap
    root = Path(exec_settings.logs.root_dir)
    gauge = LogsDirGauge(root, budget=0)
    maint_marker = b"\n[dopilot:log-truncated max_bytes=2048 reason=maintenance]\n"
    size_cap_marker = b"\n[dopilot:log-truncated max_bytes=2048 reason=size-cap]\n"
    # (a) raw cap+1, integrity intact -> must be cut (was skipped before R-03)
    _t, _e, plus_one = await _seed(db_session, exec_settings, size=cap + 1)
    # (b) already cut by the consumer: exactly cap + size-cap marker, 'truncated'
    _t, _e, settled = await _seed(db_session, exec_settings, size=cap + len(size_cap_marker))
    Path(settled.storage_path).write_bytes(b"z" * cap + size_cap_marker)
    settled.log_integrity = "truncated"
    settled.truncation_reason = "size-cap"
    # (c) legacy: marked 'truncated' by the consumer but still far above the cap
    _t, _e, legacy = await _seed(db_session, exec_settings, size=5000 + len(size_cap_marker))
    Path(legacy.storage_path).write_bytes(b"z" * 5000 + size_cap_marker)
    legacy.log_integrity = "truncated"
    legacy.truncation_reason = "size-cap"
    await db_session.commit()
    await gauge.calibrate()
    settled_mtime = Path(settled.storage_path).stat().st_mtime_ns

    cut = await maint.truncate_oversized_log_files(db_session, exec_settings, gauge=gauge)
    await db_session.commit()
    assert cut == 2
    for lf in (plus_one, legacy):
        body = Path(lf.storage_path).read_bytes()
        assert body == b"z" * cap + maint_marker
        await db_session.refresh(lf)
        assert lf.size_bytes == lf.final_offset == len(body)
        assert lf.log_integrity == "truncated" and lf.truncation_reason == "maintenance"
    assert Path(settled.storage_path).read_bytes() == b"z" * cap + size_cap_marker
    assert Path(settled.storage_path).stat().st_mtime_ns == settled_mtime
    await db_session.refresh(settled)
    assert settled.truncation_reason == "size-cap"
    assert gauge.value == walk_size(root)
    # second pass: everything is in the settled state -> nothing to cut
    assert await maint.truncate_oversized_log_files(db_session, exec_settings, gauge=gauge) == 0


# --- TC-14: evict oldest sealed tasks to the budget --------------------------------------


async def test_evict_logs_dir_to_budget(db_session, exec_settings):
    exec_settings.logs.max_total_bytes = 15 * 1024
    root = Path(exec_settings.logs.root_dir)
    gauge = LogsDirGauge(root, budget=15 * 1024)
    tasks = []
    for i in range(3):
        t, _e, lf = await _seed(db_session, exec_settings, size=10 * 1024,
                                finished_at=NOW - timedelta(days=3 - i))
        tasks.append((t, lf))
    result = await maint.evict_logs_dir_to_budget(
        db_session, exec_settings, gauge=gauge, now=NOW
    )
    assert result["evicted"] == 2 and result["recovered"] is True
    assert gauge.value == walk_size(root) <= 15 * 1024
    oldest, mid, newest = tasks
    assert not Path(oldest[1].storage_path).exists()
    assert not Path(mid[1].storage_path).exists()
    assert Path(newest[1].storage_path).exists()
    assert await db_session.get(Task, newest[0].id) is not None
    assert await db_session.get(Task, oldest[0].id) is None
    assert await _notes(db_session, TYPE_LOGS_DIR_OVER_BUDGET) == []

    # budget 0 -> no-op
    exec_settings.logs.max_total_bytes = 0
    zero = LogsDirGauge(root, budget=0)
    result = await maint.evict_logs_dir_to_budget(db_session, exec_settings, gauge=zero, now=NOW)
    assert result["evicted"] == 0 and Path(newest[1].storage_path).exists()


# --- TC-15: only active logs left -> cannot recover -> error notification ------------------


async def test_evict_cannot_recover_when_only_active_logs(db_session, exec_settings):
    exec_settings.logs.max_total_bytes = 15 * 1024
    root = Path(exec_settings.logs.root_dir)
    gauge = LogsDirGauge(root, budget=15 * 1024)
    lfs = []
    for _ in range(3):
        _t, _e, lf = await _seed(db_session, exec_settings, size=10 * 1024, log_status="active",
                                 task_status=states.TASK_RUNNING)
        lfs.append(lf)
    result = await maint.evict_logs_dir_to_budget(
        db_session, exec_settings, gauge=gauge, now=NOW
    )
    assert result["evicted"] == 0 and result["recovered"] is False
    assert all(Path(lf.storage_path).exists() for lf in lfs)
    notes = await _notes(db_session, TYPE_LOGS_DIR_OVER_BUDGET)
    assert len(notes) == 1 and notes[0].severity == "error" and notes[0].count == 1
    await maint.evict_logs_dir_to_budget(db_session, exec_settings, gauge=gauge, now=NOW)
    db_session.expire_all()
    notes = await _notes(db_session, TYPE_LOGS_DIR_OVER_BUDGET)
    assert len(notes) == 1 and notes[0].count == 2  # same day bucket folds


# --- TC-16: stale command streams ------------------------------------------------------------


async def test_delete_stale_command_streams(db_session, exec_settings, fake_redis):
    fake = fake_redis()
    settings = make_settings()
    settings.maintenance.stale_command_stream_days = 7
    old_ms = int((NOW - timedelta(days=10)).timestamp() * 1000)
    fresh_ms = int((NOW - timedelta(minutes=1)).timestamp() * 1000)

    async def stream(agent, ms):
        await fake.xadd(command_stream(agent), {b"data": b"{}"})
        # fakeredis assigns wall-clock ids; rewrite via delete + explicit id
        await fake.delete(command_stream(agent))
        await fake._c.xadd(command_stream(agent), {b"data": b"{}"}, id=f"{ms}-0")

    for agent, ms in (("ghost", old_ms), ("retired", old_ms), ("stale-hb", old_ms),
                      ("old-active", old_ms), ("agent-01", fresh_ms)):
        await stream(agent, ms)

    def node(agent, *, seen, deleted=None):
        return Node(agent_id=agent, endpoint=f"agent://{agent}", status="unknown",
                    capabilities={}, health={}, last_seen_at=seen, deleted_at=deleted)

    db_session.add_all([
        node("retired", seen=NOW - timedelta(days=30), deleted=NOW - timedelta(days=20)),
        node("stale-hb", seen=NOW - timedelta(days=30)),
        node("old-active", seen=NOW - timedelta(days=30)),
        node("agent-01", seen=NOW),
    ])
    # stale-hb: a sent outbox row still references it
    t = Task(id=new_id(), artifact_type="scrapy", target="x", status="queued", params={})
    db_session.add(t)
    db_session.add(CommandOutbox(command_id=new_id(), agent_id="stale-hb", task_id=t.id,
                                 execution_id=new_id(), type="run", payload={}, status="sent",
                                 expire_at=NOW, give_up_at=NOW))
    # old-active: a running execution
    t2 = Task(id=new_id(), artifact_type="scrapy", target="x", status="running", params={})
    db_session.add(t2)
    db_session.add(Execution(id=new_id(), task_id=t2.id, agent_id="old-active",
                             status="running", error_detail={}))
    await db_session.commit()

    deleted = await maint.delete_stale_command_streams(db_session, settings, fake, now=NOW)
    await db_session.commit()
    assert sorted(deleted) == ["ghost", "retired"]
    for agent in ("stale-hb", "old-active", "agent-01"):
        assert await fake.xlen(command_stream(agent)) == 1, agent
    for agent in ("ghost", "retired"):
        assert await fake.xlen(command_stream(agent)) == 0, agent
    notes = await _notes(db_session, TYPE_STALE_COMMAND_STREAMS_DELETED)
    assert len(notes) == 1 and sorted(notes[0].payload["agent_ids"]) == ["ghost", "retired"]
    # days 0 -> off
    settings.maintenance.stale_command_stream_days = 0
    assert await maint.delete_stale_command_streams(db_session, settings, fake, now=NOW) == []


# --- TC-27: resource stats expose the new budgets ----------------------------------------------


async def test_resource_stats_new_entries(test_sessionmaker, exec_settings, tmp_path):
    from .test_resource_stats import FakeRedis

    class _Fake(FakeRedis):
        async def memory_usage(self, key, *, samples=0):
            return 123456 if key == LOG_STREAM else None

    fake = _Fake()
    root = Path(exec_settings.logs.root_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.log").write_bytes(b"q" * 777)
    gauge = LogsDirGauge(root, budget=exec_settings.logs.max_total_bytes)
    await gauge.calibrate()
    snap = await collect_snapshot(test_sessionmaker, exec_settings, fake, now=NOW, gauge=gauge)
    entries = {e["key"]: e for s in snap["scopes"] for e in s["entries"]}
    assert entries["logs.dir_bytes"]["value"] == 777
    assert entries["logs.dir_bytes"]["limit"] == 21474836480
    assert entries["redis.stream_bytes:logs"]["limit"] == 268435456
    assert entries["redis.stream_bytes:logs"]["value"] == 123456


# --- TC-32: server startup order ------------------------------------------------------------


async def test_lifespan_runs_guard_and_gauge_before_consumers(monkeypatch, tmp_path):
    import dopilot_server.app as appmod

    order: list[str] = []
    loop = asyncio.get_running_loop()
    stamps: dict[str, float] = {}

    class _Worker:
        name = "worker"

        def __init__(self, *a, **k):
            pass

        def start(self):
            order.append(f"{self.name}.start")
            stamps[f"{self.name}.start"] = loop.time()

        async def stop(self):
            pass

    def worker(name):
        return type(name, (_Worker,), {"name": name})

    class _Guard(_Worker):
        name = "stream_guard"

        async def enforce_once(self):
            order.append("stream_guard.enforce_once")
            await asyncio.sleep(0.01)
            stamps["stream_guard.enforce_once"] = loop.time()
            return {}

    class _Gauge:
        def __init__(self, *a, **k):
            self.value = 0

        async def calibrate(self, *a, **k):
            order.append("logs_dir_gauge.calibrate")
            await asyncio.sleep(0.01)
            stamps["logs_dir_gauge.calibrate"] = loop.time()
            return 0

    class _FakeRedis:
        async def aclose(self):
            pass

    async def _noop_seed(*a, **k):
        pass

    monkeypatch.setattr(appmod, "seed_builtin_artifacts", _noop_seed)
    monkeypatch.setattr(appmod, "build_redis", lambda url: _FakeRedis())
    monkeypatch.setattr(appmod, "CommandProducer", lambda *a, **k: object())
    monkeypatch.setattr(appmod, "CommandDispatcher", worker("dispatcher"))
    monkeypatch.setattr(appmod, "EventConsumer", worker("event_consumer"))
    monkeypatch.setattr(appmod, "LogConsumer", worker("log_consumer"))
    monkeypatch.setattr(appmod, "RedisReconcileLoop", worker("reconcile"))
    monkeypatch.setattr(appmod, "RetentionSweepLoop", worker("retention"))
    monkeypatch.setattr(appmod, "ResourceStatsLoop", worker("stats"))
    monkeypatch.setattr(appmod, "StreamGuardLoop", _Guard)
    monkeypatch.setattr(appmod, "LogsDirGauge", _Gauge)
    monkeypatch.setattr(appmod, "build_schedule_runner", lambda *a, **k: None)

    settings = make_settings(logs_root=str(tmp_path / "logs"))
    app = appmod.create_app(settings)
    async with app.router.lifespan_context(app):
        pass

    assert order[:2] == ["stream_guard.enforce_once", "logs_dir_gauge.calibrate"]
    starts = [o for o in order if o.endswith(".start")]
    # exact plan order (TC-32): retention BEFORE the periodic stream guard
    assert starts[:6] == [
        "dispatcher.start", "event_consumer.start", "log_consumer.start", "reconcile.start",
        "retention.start", "stream_guard.start",
    ]
    assert order[:8] == [
        "stream_guard.enforce_once", "logs_dir_gauge.calibrate", *starts[:6],
    ]
    first_start = min(stamps[s] for s in starts)
    assert stamps["stream_guard.enforce_once"] <= first_start
    assert stamps["logs_dir_gauge.calibrate"] <= first_start
    assert isinstance(app.state.logs_gauge, _Gauge)


# --- round 3 R-01: retention never deletes an UNRECORDED schedule task ------------------


async def test_cleanup_keeps_unrecorded_schedule_tasks_until_recorded(
    db_session, exec_settings, seeder
):
    from dopilot_server.services.outcomes import record_task_outcomes

    from .test_outcomes import _schedule, _task

    exec_settings.scheduler.auto_disable_after_errors = 1000
    exec_settings.logs.retention_days = 1
    sched = await _schedule(db_session, seeder)
    old = NOW - timedelta(days=10)
    # 250 old, terminal, SEALED schedule tasks that nobody has recorded yet
    # (more than one recorder batch of 200)
    for i in range(250):
        await _task(db_session, exec_settings, sched, finished_at=old + timedelta(seconds=i))
    # plus one old direct-run task (not a schedule outcome): deletable right away
    direct, _e, _lf = await _task(
        db_session, exec_settings, None, source=states.TASK_SOURCE_DIRECT, finished_at=old
    )
    summary = await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=NOW)
    assert summary.tasks == 1  # only the direct task
    assert await db_session.get(Task, direct.id) is None
    remaining = (await db_session.execute(select(Task.id))).scalars().all()
    assert len(remaining) == 250

    # recorder batch 1 (200) -> those become deletable, the other 50 are kept
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    summary = await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=NOW)
    assert summary.tasks == 200
    assert len((await db_session.execute(select(Task.id))).scalars().all()) == 50
    # recorder batch 2 -> the rest
    await record_task_outcomes(db_session, exec_settings, now=NOW)
    await db_session.commit()
    summary = await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=NOW)
    assert summary.tasks == 50
    await db_session.refresh(sched)
    assert sched.consecutive_error_count == 250  # nothing was lost to retention


# --- round 3 R-02: a victim that cannot be unlinked does not block the rest -------------


async def test_evict_skips_failing_victim_and_continues(db_session, exec_settings, monkeypatch):
    exec_settings.logs.max_total_bytes = 15 * 1024
    root = Path(exec_settings.logs.root_dir)
    gauge = LogsDirGauge(root, budget=15 * 1024)
    tasks = []
    for i in range(3):
        t, _e, lf = await _seed(db_session, exec_settings, size=10 * 1024,
                                finished_at=NOW - timedelta(days=3 - i))
        tasks.append((t, lf))
    oldest, mid, newest = tasks
    from dopilot_server.logs import files as files_mod

    real = files_mod.aremove

    async def flaky(path):
        if path == oldest[1].storage_path:
            raise OSError("injected unlink failure")
        return await real(path)

    monkeypatch.setattr(files_mod, "aremove", flaky)
    result = await maint.evict_logs_dir_to_budget(
        db_session, exec_settings, gauge=gauge, now=NOW
    )
    # oldest failed (kept, row expired for the next sweep) and was skipped;
    # eviction continued with mid, then newest, until the budget held
    assert result["skipped"] == 1 and result["evicted"] == 2
    assert Path(oldest[1].storage_path).exists()
    assert not Path(mid[1].storage_path).exists()
    assert not Path(newest[1].storage_path).exists()
    assert gauge.value == walk_size(root) == 10 * 1024
    assert result["recovered"] is True
    await db_session.refresh(oldest[1])
    assert oldest[1].status == "expired"  # retried by the next sweep
