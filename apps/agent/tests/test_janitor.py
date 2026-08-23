"""TC-17: janitor C8 — oversized job.log truncation only for provably-stopped jobs."""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from dopilot_agent.config.settings import (
    AgentSettings,
    Capabilities,
    RedisSettings,
    ScrapydSettings,
    Settings,
)
from dopilot_agent.deps import scrapyd_logs_dir, state_dir
from dopilot_agent.janitor import AgentJanitor
from dopilot_agent.runners.python_wheel import PythonWheelRunner
from dopilot_agent.state.store import StateStore

CAP = 1024 * 1024
MARKER = f"\n[dopilot:job-log-truncated max_bytes={CAP} reason=size-cap]\n"


def _settings(workdir: Path) -> Settings:
    return Settings(
        agent=AgentSettings(
            agent_id="agent-1", workdir=str(workdir), max_job_log_bytes=CAP,
            janitor_quiet_seconds=3600,
        ),
        capabilities=Capabilities(scrapy=True, script=True),
        scrapyd=ScrapydSettings(start=False),
        redis=RedisSettings(url=""),
    )


class FakeScrapydClient:
    def __init__(self, live: set[str]) -> None:
        self.live = live
        self.calls = 0

    async def listjobs(self, project: str) -> dict:
        self.calls += 1
        return {
            "status": "ok",
            "running": [{"id": j} for j in self.live],
            "pending": [],
            "finished": [],
        }


class LockCounter:
    def __init__(self) -> None:
        self.held: list[str] = []

    @contextlib.asynccontextmanager
    async def __call__(self, execution_id: str):
        self.held.append(execution_id)
        yield


def _log(workdir: Path, job: str, *, age: float = 0.0, body: bytes | None = None) -> Path:
    path = scrapyd_logs_dir(workdir) / "demo" / "spider" / f"{job}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * (3 * CAP) if body is None else body)
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


async def test_truncates_only_provably_stopped_logs(tmp_path: Path) -> None:
    workdir = tmp_path / "agent-data"
    workdir.mkdir()
    store = StateStore(state_dir(workdir))

    # (a) state done, 3MB -> truncated
    a = _log(workdir, "job-a")
    store.create_reserved(task_id="t", execution_id="ex-a", project="demo", spider="spider")
    store.promote_started("ex-a", scrapyd_job_id="job-a", log_path=str(a))
    store.mark_done("ex-a", result="finished")
    # (b) state started, 3MB -> untouched (watchdog territory)
    b = _log(workdir, "job-b")
    store.create_reserved(task_id="t", execution_id="ex-b", project="demo", spider="spider")
    store.promote_started("ex-b", scrapyd_job_id="job-b", log_path=str(b))
    # (c) no state, scrapyd still lists the job -> untouched
    c = _log(workdir, "job-c", age=7200)
    # (d) no state, not listed, but mtime 10 minutes ago (< quiet) -> untouched
    d = _log(workdir, "job-d", age=600)
    # (e) no state, not listed, quiet for 2h -> truncated
    e = _log(workdir, "job-e", age=7200)
    # (f) R-03 boundary: raw CAP+1 with no marker, done -> truncated too
    f = _log(workdir, "job-f", body=b"x" * (CAP + 1))
    store.create_reserved(task_id="t", execution_id="ex-f", project="demo", spider="spider")
    store.promote_started("ex-f", scrapyd_job_id="job-f", log_path=str(f))
    store.mark_done("ex-f", result="finished")
    # (g) already in the CAP + marker state (here: the watchdog's marker), done
    #     -> not a candidate at all (no lock, no rewrite)
    g_body = b"x" * CAP + b"\n[dopilot:log-truncated max_bytes=1048576 reason=size-cap]\n"
    g = _log(workdir, "job-g", body=g_body, age=7200)
    store.create_reserved(task_id="t", execution_id="ex-g", project="demo", spider="spider")
    store.promote_started("ex-g", scrapyd_job_id="job-g", log_path=str(g))
    store.mark_done("ex-g", result="finished")
    g_mtime = g.stat().st_mtime_ns

    locks = LockCounter()
    scrapyd = FakeScrapydClient(live={"job-c"})
    janitor = AgentJanitor(
        settings=_settings(workdir), store=store,
        wheel_runner=PythonWheelRunner(workspace_root=workdir / "python_wheel" / "workspaces"),
        cursor_dir=str(workdir / "logpos"), artifacts_root=str(workdir / "artifacts"),
        lock_for=locks, scrapyd_client=scrapyd,
    )
    await janitor.sweep_once(now=time.time())

    bound = CAP + len(MARKER)
    assert a.stat().st_size == bound and a.read_bytes().endswith(MARKER.encode())
    assert e.stat().st_size == bound
    assert f.read_bytes() == b"x" * CAP + MARKER.encode()
    assert g.read_bytes() == g_body and g.stat().st_mtime_ns == g_mtime
    assert "ex-g" not in locks.held
    assert b.stat().st_size == 3 * CAP
    assert c.stat().st_size == 3 * CAP
    assert d.stat().st_size == 3 * CAP
    # truncation happened under the execution lock (state-less log: path key)
    assert "ex-a" in locks.held and "ex-f" in locks.held
    assert any(k.startswith("log:") and k.endswith("job-e.log") for k in locks.held)
    assert scrapyd.calls >= 1


async def test_active_set_and_missing_client_block_truncation(tmp_path: Path) -> None:
    workdir = tmp_path / "agent-data"
    workdir.mkdir()
    store = StateStore(state_dir(workdir))
    done = _log(workdir, "job-done")
    store.create_reserved(task_id="t", execution_id="ex-done", project="demo", spider="spider")
    store.promote_started("ex-done", scrapyd_job_id="job-done", log_path=str(done))
    store.mark_done("ex-done", result="finished")
    orphan = _log(workdir, "job-orphan", age=7200)

    janitor = AgentJanitor(
        settings=_settings(workdir), store=store,
        wheel_runner=PythonWheelRunner(workspace_root=workdir / "python_wheel" / "workspaces"),
        cursor_dir=str(workdir / "logpos"), artifacts_root=str(workdir / "artifacts"),
        active_ids=lambda: {"ex-done"},  # mid-flight command -> never touch
        scrapyd_client=None,  # cannot prove a state-less job is dead -> never touch
    )
    await janitor.sweep_once(now=time.time())
    assert done.stat().st_size == 3 * CAP
    assert orphan.stat().st_size == 3 * CAP
