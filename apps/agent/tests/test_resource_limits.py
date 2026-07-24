"""Resource hard-limits tests (agent side): task-resource-hard-limits.

Covers TC-08..13 (agent) and TC-17 from the plan. Each test docstring names its
TC id.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from dopilot_agent.config.settings import (
    AgentSettings,
    Capabilities,
    RedisSettings,
    ScrapydSettings,
    Settings,
)
from dopilot_agent.janitor import AgentJanitor
from dopilot_agent.redis.events import EventPublisher
from dopilot_agent.redis.logs import LogPublisher
from dopilot_agent.runners.python_wheel import PythonWheelRunner
from dopilot_agent.scrapyd.process import ScrapydProcess
from dopilot_agent.state.store import AttemptState, StateStore
from dopilot_protocol import LOG_STREAM


def _settings(workdir: Path, **agent_over) -> Settings:
    agent = AgentSettings(agent_id="agent-1", workdir=str(workdir), **agent_over)
    return Settings(
        agent=agent,
        capabilities=Capabilities(scrapy=True, script=True),
        scrapyd=ScrapydSettings(start=False),
        redis=RedisSettings(url=""),
    )


def _age(path: Path, seconds_old: float) -> None:
    """Set mtime of every file under ``path`` (and the dir) to now-seconds_old."""
    t = time.time() - seconds_old
    for p in [path, *path.rglob("*")]:
        try:
            os.utime(p, (t, t))
        except OSError:
            pass


# --------------------------------------------------------------------------
# TC-08 — janitor workspace/orphan GC with the three-guard safety
# --------------------------------------------------------------------------
async def test_tc08_janitor_workspace_and_orphan_gc(tmp_path, monkeypatch):
    """TC-08: only terminal>ttl and fully-guarded orphans are removed; running,
    fresh, pgid-alive and corrupt-but-alive workspaces are kept."""
    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "state" / "executions" / "logpos"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    ws_root = workdir / "python_wheel" / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)

    runner = PythonWheelRunner(workspace_root=str(ws_root))
    monkeypatch.setattr(runner, "active_execution_ids", lambda: {"running_active"})

    dead_pgid = 2**30  # certainly no such process group
    live_pgid = os.getpgid(os.getpid())

    def mkws(name: str, *, pgid: int | None = None) -> Path:
        d = ws_root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "job.log").write_text("x", encoding="utf-8")
        if pgid is not None:
            (d / "job.pgid").write_text(str(pgid), encoding="utf-8")
        (cursor_dir / f"{name}.logpos").write_text("0", encoding="utf-8")
        return d

    def mkstate(eid: str, phase: str) -> None:
        store.write(AttemptState(
            task_id="t", execution_id=eid, phase=phase,
            result="finished" if phase == "done" else None,
            runner_type="python_wheel",
        ))

    # scenarios
    term_old = mkws("term_old", pgid=dead_pgid)
    mkstate("term_old", "done")
    term_new = mkws("term_new", pgid=dead_pgid)
    mkstate("term_new", "done")
    running = mkws("running_active", pgid=live_pgid)
    mkstate("running_active", "started")
    orphan_dead = mkws("orphan_dead", pgid=dead_pgid)  # no state
    corrupt_alive = mkws("corrupt_alive", pgid=live_pgid)
    (store.dir / "corrupt_alive.json").write_text("{bad json", encoding="utf-8")
    corrupt_dead = mkws("corrupt_dead", pgid=dead_pgid)  # corrupt state, pgid dead
    (store.dir / "corrupt_dead.json").write_text("{bad json", encoding="utf-8")
    orphan_fresh = mkws("orphan_fresh", pgid=dead_pgid)  # no state, fresh

    # ages: old ones well beyond both TTLs; fresh ones are new.
    for d in (term_old, orphan_dead, corrupt_alive, corrupt_dead, running):
        _age(d, seconds_old=40 * 86400)
    # term_new / orphan_fresh stay fresh (mtime ~ now)

    released: list[str] = []
    janitor = AgentJanitor(
        settings=_settings(
            workdir, completed_log_ttl_days=3, orphan_log_ttl_days=7,
        ),
        store=store, wheel_runner=runner, cursor_dir=str(cursor_dir),
        artifacts_root=str(workdir / "artifacts"),
        release=released.append,
    )
    await janitor.sweep_once(now=time.time())

    # removed: terminal>3d, fully-guarded orphan (no state, pgid dead, quiet>7d),
    # and corrupt-state + pgid dead + quiet>7d (a corrupt state is recoverable).
    assert not term_old.exists()
    assert not orphan_dead.exists()
    assert not corrupt_dead.exists()
    assert not (cursor_dir / "term_old.logpos").exists()  # .logpos cleaned too
    assert set(released) == {"term_old", "orphan_dead", "corrupt_dead"}
    # kept: fresh terminal, running (active set), corrupt-state-but-pgid-alive,
    # fresh orphan.
    assert term_new.exists()
    assert running.exists()
    assert corrupt_alive.exists()   # pgid alive -> never removed
    assert orphan_fresh.exists()    # within orphan ttl -> kept


async def test_tc08_janitor_respects_inflight_and_lock_recheck(tmp_path):
    """TC-08 (R-04 race): a workspace whose command is mid-flight (in the active
    set) is never deleted even when old/quiet/no-pgid; and an id that becomes
    active only between the scan and the locked commit is spared by the fresh
    re-check under the per-execution lock."""
    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "logpos"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    ws_root = workdir / "python_wheel" / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    runner = PythonWheelRunner(workspace_root=str(ws_root))

    def mkws(name: str) -> Path:
        d = ws_root / name
        d.mkdir(parents=True)
        (d / "job.log").write_text("x", encoding="utf-8")
        _age(d, seconds_old=40 * 86400)  # old + quiet, no pgid sidecar
        return d

    inflight = mkws("inflight")          # in active set the whole time -> kept
    racy = mkws("racy")                  # becomes active between scan and commit

    # active_ids: inflight is always active; racy flips to active after the first
    # call (the scan) so the locked re-check sees it and spares it.
    calls = {"n": 0}

    def active_ids() -> set[str]:
        calls["n"] += 1
        base = {"inflight"}
        return base | ({"racy"} if calls["n"] > 1 else set())

    locks: dict[str, asyncio.Lock] = {}

    def lock_for(eid: str) -> asyncio.Lock:
        return locks.setdefault(eid, asyncio.Lock())

    janitor = AgentJanitor(
        settings=_settings(workdir, orphan_log_ttl_days=7),
        store=store, wheel_runner=runner, cursor_dir=str(cursor_dir),
        artifacts_root=str(workdir / "artifacts"),
        active_ids=active_ids, lock_for=lock_for,
    )
    await janitor.sweep_once(now=time.time())

    assert inflight.exists()  # active throughout -> never scanned as candidate
    assert racy.exists()      # became active before the locked delete -> spared


async def test_tc17_refcounted_lock_never_orphaned_while_held(tmp_path):
    """TC-17 (R-02): the per-execution keyed lock is never removed while a holder
    or waiter exists (so two coroutines can never hold two different locks for the
    same execution), and it IS removed once the last one leaves (no leak).
    _release_execution must not disturb the lock lifecycle."""
    from dopilot_agent.redis.commands import CommandConsumer
    from dopilot_agent.runners.scrapyd import ScrapyRunner
    from dopilot_agent.scrapyd.client import ScrapydClient

    store = StateStore(str(tmp_path / "state"))
    consumer = CommandConsumer(
        redis=object(), agent_id="a1",
        runner=ScrapyRunner(
            client=ScrapydClient(base_url="http://x"), store=store,
            logs_dir=str(tmp_path / "logs"),
        ),
        store=store, events=None,
    )
    eid = "e1"
    seen_locks: list[int] = []
    a_holds = asyncio.Event()
    b_may_finish = asyncio.Event()

    async def holder_a():
        async with consumer._execution_lock(eid):
            seen_locks.append(id(consumer._locks[eid][0]))
            a_holds.set()
            await b_may_finish.wait()  # keep holding while B waits + release runs

    async def waiter_b():
        await a_holds.wait()
        # B now waits on the SAME lock (refcount 2).
        async with consumer._execution_lock(eid):
            seen_locks.append(id(consumer._locks[eid][0]))

    ta = asyncio.create_task(holder_a())
    await a_holds.wait()
    tb = asyncio.create_task(waiter_b())
    await asyncio.sleep(0)  # let B register as a waiter (refcount -> 2)
    assert consumer._locks[eid][1] == 2

    # A cleanup-style release while the lock is held must NOT drop the mapping.
    consumer._release_execution(eid)
    assert eid in consumer._locks

    b_may_finish.set()
    await asyncio.gather(ta, tb)
    # Same lock object served both; entry removed only after the last left.
    assert seen_locks[0] == seen_locks[1]
    assert eid not in consumer._locks


async def test_tc11_cache_eviction_skips_locked_entry(tmp_path):
    """TC-11 (R-03): a cache entry whose .lock is held (install/reuse in flight)
    is skipped by eviction; once the lock is gone it is evicted."""
    workdir = tmp_path
    artifacts = workdir / "artifacts"
    scrapy = artifacts / "scrapy"
    scrapy.mkdir(parents=True)
    store = StateStore(str(workdir / "state"))
    runner = PythonWheelRunner(workspace_root=str(workdir / "ws"))

    sha = "locked-sha"
    (scrapy / f"{sha}.egg").write_bytes(b"e" * 2000)
    (scrapy / f"{sha}.egg.ready").write_text("", encoding="utf-8")
    lock = scrapy / f"{sha}.egg.lock"
    lock.write_text("", encoding="utf-8")  # install/reuse in flight

    janitor = AgentJanitor(
        settings=_settings(workdir, artifact_cache_max_bytes=100),  # over cap
        store=store, wheel_runner=runner,
        cursor_dir=str(workdir / "logpos"), artifacts_root=str(artifacts),
    )
    janitor._sweep_cache()
    assert (scrapy / f"{sha}.egg").exists()  # locked -> not evicted

    # Lock released -> eviction proceeds next sweep.
    lock.unlink()
    janitor._sweep_cache()
    assert not (scrapy / f"{sha}.egg").exists()


# --------------------------------------------------------------------------
# TC-09 — job.log size cap via PIPE drain, no backpressure block
# --------------------------------------------------------------------------
async def test_tc09_job_log_size_cap_no_block(tmp_path):
    """TC-09: a job that writes far more than the pipe buffer + the cap still
    exits normally; job.log is bounded to cap + one marker; drain finishes."""
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    cap = 8192
    runner = PythonWheelRunner(workspace_root=str(ws_root), max_job_log_bytes=cap)
    install = tmp_path / "site"
    install.mkdir()

    eid = "wheel-1"
    # ~2 MiB of output — far exceeds the 64 KiB OS pipe buffer and the 8 KiB cap.
    cmd = "i=0; while [ $i -lt 100000 ]; do echo xxxxxxxxxxxxxxxxxxxx; i=$((i+1)); done"
    started = await runner.start(
        execution_id=eid, task_id="t", shell_command=cmd,
        install_path=str(install),
    )
    outcome = await asyncio.wait_for(runner.wait(eid), timeout=30)
    assert outcome.exit_code == 0  # not blocked / not killed

    body = Path(started.log_path).read_bytes()
    assert body.count(b"job-log-truncated") == 1
    assert len(body) <= cap + 128  # cap + one marker line
    # The reaper awaited the drain to EOF and closed the log file handle.
    assert eid not in runner._logs
    await runner.aclose()


# --------------------------------------------------------------------------
# TC-10 — scrapyd.conf retention keys
# --------------------------------------------------------------------------
def test_tc10_scrapyd_conf_retention_keys(tmp_path):
    """TC-10: generated scrapyd.conf carries jobs_to_keep / finished_to_keep
    (defaults and custom values)."""
    default = ScrapydProcess(workdir=str(tmp_path / "a"))
    conf = default.write_conf().read_text(encoding="utf-8")
    assert "jobs_to_keep = 5" in conf
    assert "finished_to_keep = 100" in conf

    custom = ScrapydProcess(
        workdir=str(tmp_path / "b"), jobs_to_keep=7, finished_to_keep=42
    )
    conf2 = custom.write_conf().read_text(encoding="utf-8")
    assert "jobs_to_keep = 7" in conf2
    assert "finished_to_keep = 42" in conf2


# --------------------------------------------------------------------------
# TC-11 — artifact cache LRU eviction
# --------------------------------------------------------------------------
async def test_tc11_cache_lru_eviction(tmp_path, monkeypatch):
    """TC-11: over the cap, least-recently-used cache entries are evicted;
    a referenced sha is never evicted; cap=0 disables eviction."""
    workdir = tmp_path
    artifacts = workdir / "artifacts"
    scrapy = artifacts / "scrapy"
    wheel = artifacts / "python_wheel"
    scrapy.mkdir(parents=True)
    wheel.mkdir(parents=True)
    store = StateStore(str(workdir / "state" / "executions"))
    runner = PythonWheelRunner(workspace_root=str(workdir / "ws"))

    def mkegg(sha: str, size: int, mtime_age: float):
        (scrapy / f"{sha}.egg").write_bytes(b"e" * size)
        ready = scrapy / f"{sha}.egg.ready"
        ready.write_text("", encoding="utf-8")
        t = time.time() - mtime_age
        os.utime(ready, (t, t))

    def mkwheel(sha: str, size: int, mtime_age: float):
        d = wheel / sha
        (d / "site").mkdir(parents=True)
        (d / "site" / "pkg").write_bytes(b"w" * size)
        ready = d / ".ready"
        ready.write_text("", encoding="utf-8")
        t = time.time() - mtime_age
        os.utime(ready, (t, t))

    mkegg("aaa", 500, mtime_age=100)      # oldest -> evicted first
    mkwheel("bbb", 500, mtime_age=50)     # middle
    mkwheel("ccc", 500, mtime_age=10)     # newest but REFERENCED -> kept

    # ccc is referenced by a running (non-terminal) wheel execution.
    store.write(AttemptState(
        task_id="t", execution_id="run-1", phase="started",
        runner_type="python_wheel",
        install_path=str(wheel / "ccc" / "site"),
    ))

    settings = _settings(workdir, artifact_cache_max_bytes=1200)  # total 1500 > cap
    janitor = AgentJanitor(
        settings=settings, store=store, wheel_runner=runner,
        cursor_dir=str(workdir / "logpos"), artifacts_root=str(artifacts),
    )
    janitor._sweep_cache()

    # total 1500, cap 1200 -> must drop >=300 bytes; LRU order aaa then bbb, but
    # dropping aaa (500) already brings it to 1000 <= 1200, so only aaa evicted.
    assert not (scrapy / "aaa.egg").exists()
    assert (wheel / "bbb").exists()
    assert (wheel / "ccc").exists()  # referenced -> never evicted

    # cap=0 disables eviction: recreate aaa and confirm it survives.
    mkegg("aaa", 500, mtime_age=100)
    settings.agent.artifact_cache_max_bytes = 0
    janitor._sweep_cache()
    assert (scrapy / "aaa.egg").exists()


# --------------------------------------------------------------------------
# TC-12 — event outbox file-count cap (drop oldest)
# --------------------------------------------------------------------------
class _FailingRedis:
    async def xadd(self, *a, **k):
        raise RuntimeError("redis down")


async def test_tc12_outbox_cap_drops_oldest(tmp_path, caplog):
    """TC-12: with the outbox at its cap, persisting a new event drops the oldest
    file so the count stays bounded, and logs the drop at ERROR."""
    import logging

    outbox = tmp_path / "outbox"
    outbox.mkdir()
    # Pre-seed 3 old outbox files with increasing mtimes.
    for i in range(3):
        f = outbox / f"old-{i}.json"
        f.write_text("{}", encoding="utf-8")
        t = time.time() - (100 - i)  # old-0 is the OLDEST
        os.utime(f, (t, t))

    pub = EventPublisher(
        redis=_FailingRedis(), agent_id="agent-1", runner=None,
        store=StateStore(str(tmp_path / "state")),
        outbox_dir=str(outbox), max_outbox_files=3,
    )
    # emit persists (cap enforced first: drops oldest to make room), then the
    # failing xadd leaves the new file durably queued.
    with caplog.at_level(logging.ERROR, logger="dopilot_agent.redis.events"):
        await pub.emit_accepted("t", "exec-new")

    files = sorted(p.name for p in outbox.glob("*.json"))
    assert len(files) == 3                    # count stayed bounded
    assert "old-0.json" not in files          # oldest dropped
    assert any(not name.startswith("old-") for name in files)  # new one present
    # The drop was logged at ERROR (observability of a lossy outage state).
    assert any(
        "over cap" in rec.message and rec.levelno == logging.ERROR
        for rec in caplog.records
    )


# --------------------------------------------------------------------------
# TC-17 — consumer bookkeeping lifecycle + EOF idempotency (C6)
# --------------------------------------------------------------------------
class _RecordingRedis:
    def __init__(self):
        self.log_xadds = 0

    async def xadd(self, stream, fields, *, maxlen=None, approximate=True):
        if stream == LOG_STREAM:
            self.log_xadds += 1
        return b"1-0"


@pytest.mark.parametrize("result", ["finished", "failed", "canceled"])
async def test_tc17_bookkeeping_lifetime_and_eof_idempotent(tmp_path, result):
    """TC-17: for EACH terminal result (finished/failed/canceled), at terminal+EOF
    the in-proc-wheel + runner bookkeeping are released while the EOF dedup + lock
    persist; EOF is published only once across many ticks (repeated terminal is
    idempotent); state cleanup then releases the lock + cursor."""
    from dopilot_agent.redis.commands import CommandConsumer
    from dopilot_agent.runners.scrapyd import ScrapyRunner
    from dopilot_agent.scrapyd.client import ScrapydClient

    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "logpos"
    runner = PythonWheelRunner(workspace_root=str(workdir / "ws"))
    redis = _RecordingRedis()

    eid = "exec-1"
    log_file = workdir / "job.log"
    log_file.write_text("some output\n", encoding="utf-8")
    store.write(AttemptState(
        task_id="t", execution_id=eid, phase="done", result=result,
        canceled=(result == "canceled"),
        runner_type="python_wheel", log_path=str(log_file),
    ))

    consumer = CommandConsumer(
        redis=redis, agent_id="agent-1",
        runner=ScrapyRunner(
            client=ScrapydClient(base_url="http://x"), store=store,
            logs_dir=str(workdir / "scrapyd" / "logs"),
        ),
        store=store, events=None, wheel_runner=runner,
    )
    log_pub = LogPublisher(
        redis=redis, agent_id="agent-1", store=store,
        cursor_dir=str(cursor_dir), on_eof=consumer.on_execution_eof,
    )
    consumer.set_log_publisher(log_pub)

    # Seed the per-execution bookkeeping that a live wheel run would hold.
    consumer._inproc_wheel.add(eid)
    runner._procs[eid] = object()
    runner._pgids[eid] = 123
    runner._canceled.add(eid)

    # First tick: publishes the body then EOF, firing on_eof.
    await log_pub.publish_attempt(eid)
    assert redis.log_xadds >= 2                 # body + eof
    eof_after_first = redis.log_xadds
    # EOF-safe bookkeeping released:
    assert eid not in consumer._inproc_wheel
    assert eid not in runner._procs
    assert eid not in runner._pgids
    # EOF dedup RETAINED (still needed until state cleanup):
    assert eid in log_pub._eof_sent

    # Many more ticks: EOF is NOT re-published (idempotent).
    for _ in range(3):
        await log_pub.publish_attempt(eid)
    assert redis.log_xadds == eof_after_first

    # State cleanup runs INSIDE the per-execution lock (as _process does) and
    # releases the EOF dedup + .logpos cursor. The lock entry itself is owned by
    # the refcounted keyed lock (R-02): it is removed when the CM exits (refcount
    # back to 0), NOT popped by cleanup while held.
    from dopilot_protocol import AgentCommand

    cmd = AgentCommand(
        command_id="c1", agent_id="agent-1", task_id="t",
        execution_id=eid, type="cleanup_logs",
        created_at="2026-07-24T00:00:00+00:00",
    )
    async with consumer._execution_lock(eid):
        assert eid in consumer._locks           # held -> entry present
        await consumer._handle_cleanup(cmd)
        assert eid in consumer._locks           # NOT popped while held (R-02)
    assert eid not in consumer._locks           # removed at refcount 0 on exit
    assert eid not in log_pub._eof_sent
    assert not (cursor_dir / f"{eid}.logpos").exists()


# --------------------------------------------------------------------------
# TC-13 (agent) — settings defaults + env overrides
# --------------------------------------------------------------------------
def test_tc13_agent_defaults_and_env_overrides(monkeypatch, tmp_path):
    """TC-13 (agent): new [agent]/[redis]/[scrapyd] fields load from TOML with
    correct defaults; DOPILOT_REDIS_STREAM_MAXLEN_* env overrides win."""
    from dopilot_agent.config.loader import load_settings

    toml = tmp_path / "agent.toml"
    toml.write_text('[agent]\nagent_id = "a1"\n', encoding="utf-8")
    s = load_settings(str(toml))
    assert s.agent.janitor_interval_seconds == 600
    assert s.agent.completed_log_ttl_days == 3
    assert s.agent.orphan_log_ttl_days == 7
    assert s.agent.max_job_log_bytes == 104857600
    assert s.agent.artifact_cache_max_bytes == 2147483648
    assert s.redis.maxlen_logs == 100000
    assert s.redis.maxlen_events == 100000
    assert s.redis.event_outbox_max_files == 100000
    assert s.scrapyd.jobs_to_keep == 5
    assert s.scrapyd.finished_to_keep == 100

    # Every new numeric knob is overridable via env (TOML + env dual channel).
    env = {
        "DOPILOT_REDIS_STREAM_MAXLEN_LOGS": ("321", lambda s: s.redis.maxlen_logs),
        "DOPILOT_REDIS_STREAM_MAXLEN_EVENTS": (
            "654", lambda s: s.redis.maxlen_events),
        "DOPILOT_REDIS_EVENT_OUTBOX_MAX_FILES": (
            "42", lambda s: s.redis.event_outbox_max_files),
        "DOPILOT_AGENT_JANITOR_INTERVAL_SECONDS": (
            "11", lambda s: s.agent.janitor_interval_seconds),
        "DOPILOT_AGENT_COMPLETED_LOG_TTL_DAYS": (
            "2", lambda s: s.agent.completed_log_ttl_days),
        "DOPILOT_AGENT_ORPHAN_LOG_TTL_DAYS": (
            "5", lambda s: s.agent.orphan_log_ttl_days),
        "DOPILOT_AGENT_MAX_JOB_LOG_BYTES": (
            "123", lambda s: s.agent.max_job_log_bytes),
        "DOPILOT_AGENT_ARTIFACT_CACHE_MAX_BYTES": (
            "456", lambda s: s.agent.artifact_cache_max_bytes),
        "DOPILOT_SCRAPYD_JOBS_TO_KEEP": ("3", lambda s: s.scrapyd.jobs_to_keep),
        "DOPILOT_SCRAPYD_FINISHED_TO_KEEP": (
            "7", lambda s: s.scrapyd.finished_to_keep),
    }
    for var, (val, _get) in env.items():
        monkeypatch.setenv(var, val)
    s2 = load_settings(str(toml))
    for _var, (val, get) in env.items():
        assert get(s2) == int(val)


# --------------------------------------------------------------------------
# TC-09 — janitor disk sample (resource dashboard, D1)
# --------------------------------------------------------------------------
async def test_tc09_janitor_disk_sample(tmp_path, monkeypatch):
    """TC-09: sweep_once publishes a fixed-shape disk sample whose counts/bytes
    match a known workdir tree; a failing sub-item is nulled, not fatal."""
    from dopilot_agent.disk_status import DiskStatus

    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "state" / "executions" / "logpos"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    ws_root = workdir / "python_wheel" / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)

    # workspaces: 2 dirs, 100 + 50 bytes
    (ws_root / "e1").mkdir()
    (ws_root / "e1" / "job.log").write_bytes(b"x" * 100)
    (ws_root / "e2").mkdir()
    (ws_root / "e2" / "job.log").write_bytes(b"y" * 50)
    # artifact cache: 30 bytes under artifacts/scrapy
    arts = workdir / "artifacts" / "scrapy"
    arts.mkdir(parents=True)
    (arts / "abc.egg").write_bytes(b"z" * 30)
    # scrapyd dirs: 25 bytes
    scrapyd_logs = workdir / "scrapyd" / "logs"
    scrapyd_logs.mkdir(parents=True)
    (scrapyd_logs / "j.log").write_bytes(b"s" * 25)
    # outbox: 3 json files
    outbox = workdir / "outbox"
    outbox.mkdir()
    for i in range(3):
        (outbox / f"{i}.json").write_bytes(b"{}")
    # state: 2 execution state files + 2 logpos cursors
    store.write(AttemptState(task_id="t", execution_id="e1", phase="done",
                             runner_type="python_wheel"))
    store.write(AttemptState(task_id="t", execution_id="e2", phase="done",
                             runner_type="python_wheel"))
    (cursor_dir / "e1.logpos").write_text("0")
    (cursor_dir / "e2.logpos").write_text("0")

    settings = Settings(
        agent=AgentSettings(agent_id="agent-1", workdir=str(workdir),
                            janitor_interval_seconds=600),
        capabilities=Capabilities(scrapy=True),
        scrapyd=ScrapydSettings(start=False),
        redis=RedisSettings(url="", event_outbox_dir=str(outbox)),
    )
    disk = DiskStatus()
    runner = PythonWheelRunner(workspace_root=str(ws_root))
    janitor = AgentJanitor(
        settings=settings, store=store, wheel_runner=runner,
        cursor_dir=str(cursor_dir), artifacts_root=str(workdir / "artifacts"),
        disk_status=disk,
    )
    await janitor.sweep_once(now=time.time())

    sample = disk.snapshot()
    assert sample is not None
    assert set(sample) >= {
        "sampled_at", "interval_seconds", "workspaces", "cache",
        "scrapyd", "outbox", "state", "volume",
    }
    assert sample["interval_seconds"] == 600
    assert sample["workspaces"] == {"count": 2, "bytes": 150}
    assert sample["cache"]["bytes"] == 30
    assert sample["cache"]["limit"] == settings.agent.artifact_cache_max_bytes
    assert sample["scrapyd"]["bytes"] == 25
    assert sample["outbox"]["files"] == 3
    assert sample["outbox"]["limit"] == settings.redis.event_outbox_max_files
    assert sample["state"] == {"executions": 2, "logpos": 2}
    assert sample["volume"]["total"] > 0


async def test_tc09_janitor_disk_sample_subitem_failure_nulled(
    tmp_path, monkeypatch
):
    """TC-09 (edge): a failing sub-collector nulls only its item; the sweep and
    the rest of the sample survive."""
    from dopilot_agent import janitor as janitor_mod
    from dopilot_agent.disk_status import DiskStatus

    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "state" / "executions" / "logpos"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (workdir / "python_wheel" / "workspaces").mkdir(parents=True)

    def _boom(_path):
        raise OSError("volume unreadable")

    monkeypatch.setattr(janitor_mod, "_volume", _boom)

    settings = _settings(workdir)
    disk = DiskStatus()
    runner = PythonWheelRunner(
        workspace_root=str(workdir / "python_wheel" / "workspaces")
    )
    janitor = AgentJanitor(
        settings=settings, store=store, wheel_runner=runner,
        cursor_dir=str(cursor_dir), artifacts_root=str(workdir / "artifacts"),
        disk_status=disk,
    )
    await janitor.sweep_once(now=time.time())
    sample = disk.snapshot()
    assert sample is not None
    assert sample["volume"] is None  # failing item nulled


def test_tc09_dir_bytes_missing_vs_access_failure(tmp_path, monkeypatch):
    """TC-09: the sample size helper returns 0 for an absent dir (legit empty)
    but PROPAGATES an access failure (so _guard nulls the item) — an unreadable
    dir is never a fake 0."""
    from dopilot_agent import janitor as janitor_mod

    # missing dir -> 0 (nothing written yet)
    assert janitor_mod._dir_bytes(tmp_path / "never") == 0

    # existing but unreadable dir -> os.walk onerror raises -> propagates
    d = tmp_path / "logs"
    d.mkdir()

    def _walk(path, onerror=None):
        if onerror is not None:
            onerror(PermissionError("denied"))
        return iter([])

    monkeypatch.setattr(janitor_mod.os, "walk", _walk)
    with pytest.raises(PermissionError):
        janitor_mod._dir_bytes(d)


def test_tc09_count_helpers_missing_vs_access_failure(tmp_path, monkeypatch):
    """TC-09: count helpers return 0 ONLY for an absent dir (FileNotFoundError);
    a PermissionError propagates (never a fake 0), and they do not rely on
    error-swallowing Path.glob/Path.exists."""
    from dopilot_agent import janitor as janitor_mod

    d = tmp_path / "logpos"
    d.mkdir()
    (d / "a.logpos").write_text("0")
    (d / "b.logpos").write_text("0")
    (d / "c.txt").write_text("x")
    # happy path: pattern match count
    assert janitor_mod._count_glob(d, "*.logpos") == 2
    assert janitor_mod._count_dirs(tmp_path) == 1  # only 'logpos' subdir

    # absent dir -> 0
    assert janitor_mod._count_glob(tmp_path / "nope", "*.logpos") == 0
    assert janitor_mod._count_dirs(tmp_path / "nope") == 0

    # unreadable dir (scandir PermissionError) -> propagates, NOT a fake 0
    def _boom_scandir(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(janitor_mod.os, "scandir", _boom_scandir)
    with pytest.raises(PermissionError):
        janitor_mod._count_glob(d, "*.logpos")
    with pytest.raises(PermissionError):
        janitor_mod._count_dirs(d)


def test_tc09_count_dirs_entry_access_failure_propagates(tmp_path, monkeypatch):
    """TC-09 (R-01): a PermissionError from DirEntry.is_dir() PROPAGATES (never a
    too-small "normal" count); only a vanished entry (FileNotFoundError) is
    skipped."""
    from dopilot_agent import janitor as janitor_mod

    class _Entry:
        def __init__(self, exc):
            self.name = "x"
            self._exc = exc

        def is_dir(self):
            if self._exc:
                raise self._exc
            return True

    # PermissionError on an entry -> propagates
    monkeypatch.setattr(
        janitor_mod.os, "scandir", lambda p: [_Entry(PermissionError("denied"))]
    )
    with pytest.raises(PermissionError):
        janitor_mod._count_dirs(tmp_path)

    # A vanished entry (FileNotFoundError) is skipped, real dirs still counted
    monkeypatch.setattr(
        janitor_mod.os,
        "scandir",
        lambda p: [_Entry(FileNotFoundError()), _Entry(None)],
    )
    assert janitor_mod._count_dirs(tmp_path) == 1


async def test_tc09_cache_sample_reflects_post_eviction_size(tmp_path):
    """TC-09 (R-02): after the LRU eviction frees space, the disk sample reports
    the REMAINING cache size, not the pre-eviction total (which could keep the
    dashboard at warn/critical for a whole janitor cycle)."""
    from dopilot_agent.disk_status import DiskStatus

    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "state" / "executions" / "logpos"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (workdir / "python_wheel" / "workspaces").mkdir(parents=True)
    wheel = workdir / "artifacts" / "python_wheel"
    for sha, age in (("aaa", 1000), ("bbb", 0)):  # aaa older -> evicted first
        d = wheel / sha
        d.mkdir(parents=True)
        (d / "body.bin").write_bytes(b"x" * 100)
        ready = d / ".ready"
        ready.write_text("")
        t = time.time() - age
        os.utime(ready, (t, t))

    # cap 150 < 200 total -> exactly one 100-byte entry is evicted, 100 remains.
    settings = _settings(workdir, artifact_cache_max_bytes=150)
    disk = DiskStatus()
    runner = PythonWheelRunner(
        workspace_root=str(workdir / "python_wheel" / "workspaces")
    )
    janitor = AgentJanitor(
        settings=settings, store=store, wheel_runner=runner,
        cursor_dir=str(cursor_dir), artifacts_root=str(workdir / "artifacts"),
        disk_status=disk,
    )
    await janitor.sweep_once(now=time.time())
    sample = disk.snapshot()
    assert sample["cache"]["bytes"] == 100  # post-eviction remaining, not 200
    assert not (wheel / "aaa").exists()  # older entry actually evicted


async def test_tc09_janitor_disk_sample_unreadable_dir_nulled(
    tmp_path, monkeypatch
):
    """TC-09 (edge): an UNREADABLE directory in the real traversal path nulls
    only that sub-item (scrapyd here) — not a fake 0 — and the rest survive."""
    from dopilot_agent import janitor as janitor_mod
    from dopilot_agent.disk_status import DiskStatus

    workdir = tmp_path
    store = StateStore(str(workdir / "state" / "executions"))
    cursor_dir = workdir / "state" / "executions" / "logpos"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    ws_root = workdir / "python_wheel" / "workspaces"
    ws_root.mkdir(parents=True)
    (ws_root / "e1").mkdir()
    (ws_root / "e1" / "job.log").write_bytes(b"x" * 10)
    (workdir / "scrapyd").mkdir()

    real_walk = janitor_mod.os.walk

    def _walk(path, onerror=None):
        # Simulate scrapyd/ being unreadable; everything else walks normally.
        if "scrapyd" in str(path) and onerror is not None:
            onerror(PermissionError("scrapyd unreadable"))
            return iter([])
        return real_walk(path, onerror=onerror)

    monkeypatch.setattr(janitor_mod.os, "walk", _walk)

    settings = _settings(workdir)
    disk = DiskStatus()
    runner = PythonWheelRunner(workspace_root=str(ws_root))
    janitor = AgentJanitor(
        settings=settings, store=store, wheel_runner=runner,
        cursor_dir=str(cursor_dir), artifacts_root=str(workdir / "artifacts"),
        disk_status=disk,
    )
    await janitor.sweep_once(now=time.time())
    sample = disk.snapshot()
    assert sample is not None
    assert sample["scrapyd"] is None  # unreadable -> nulled, NOT a fake 0
    assert sample["workspaces"]["bytes"] == 10  # others intact
    assert sample["workspaces"] is not None  # others intact
