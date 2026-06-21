"""Agent Python-wheel runner tests (phase 2b packet 2).

Covers the ``task_type=="python_wheel"`` command branch end to end with a fake
wheel cache (fast shell commands, no pip), the real :class:`PythonWheelCache`
install (``--no-deps --target``, idempotent by sha256), cancellation /
reclaim / recovery, log publishing, and an offline smoke of the built-in demo
wheel against a local HTTP server.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import http.server
import os
import shlex
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest
from dopilot_agent.artifacts.wheel_cache import PythonWheelCache, WheelCacheError
from dopilot_agent.deps import (
    scrapyd_logs_dir,
    state_dir,
    wheel_workspace_dir,
)
from dopilot_agent.redis.commands import CommandConsumer
from dopilot_agent.redis.events import EventPublisher
from dopilot_agent.redis.logs import LogPublisher
from dopilot_agent.runners.python_wheel import PythonWheelRunner
from dopilot_agent.runners.scrapyd import ScrapyRunner
from dopilot_agent.scrapyd.client import ScrapydClient
from dopilot_agent.state.store import StateStore
from dopilot_protocol import (
    EVENT_STREAM,
    LOG_STREAM,
    AgentCommand,
    AgentCommandType,
    AgentEvent,
    AgentEventType,
    AgentLogEvent,
    StopIntent,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)

from .conftest import FakeScrapyd

AGENT_ID = "agent-w"
STREAM = command_stream(AGENT_ID)

DEMO_WHEEL = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "python_wheel_demo"
    / "dopilot_demo-0.1.0-py3-none-any.whl"
)


# --------------------------------------------------------------------------- #
# Fakes / builders
# --------------------------------------------------------------------------- #
class FakeWheelCache:
    """Returns a prepared (empty) site dir; records calls; optional error."""

    def __init__(self, site_dir: Path) -> None:
        self._site = site_dir
        self._site.mkdir(parents=True, exist_ok=True)
        self.calls: list[tuple[dict, str]] = []
        self.error: WheelCacheError | None = None

    async def ensure(self, artifact: dict, *, execution_id: str) -> str:
        self.calls.append((artifact, execution_id))
        if self.error is not None:
            raise self.error
        return str(self._site)


def _build(
    workdir: Path,
    fake_redis,
    *,
    wheel_cache=None,
    grace_seconds: float = 0.3,
):
    scrapyd = FakeScrapyd()
    client = ScrapydClient(
        base_url="http://scrapyd.test", transport=scrapyd.transport()
    )
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client, store=store, logs_dir=scrapyd_logs_dir(workdir)
    )
    wheel_runner = PythonWheelRunner(
        workspace_root=wheel_workspace_dir(workdir), grace_seconds=grace_seconds
    )
    if wheel_cache is None:
        wheel_cache = FakeWheelCache(workdir / "site")
    publisher = EventPublisher(
        redis=fake_redis, agent_id=AGENT_ID, runner=runner, store=store
    )
    consumer = CommandConsumer(
        redis=fake_redis,
        agent_id=AGENT_ID,
        runner=runner,
        store=store,
        events=publisher,
        pending_idle_ms=0,
        wheel_runner=wheel_runner,
        wheel_cache=wheel_cache,
    )
    return store, runner, wheel_runner, wheel_cache, consumer, scrapyd


def _wheel_cmd(
    *,
    execution_id="w1",
    task_id="t1",
    shell_command="echo hello",
    artifact=None,
    env=None,
    working_dir=None,
) -> AgentCommand:
    if artifact is None:
        artifact = {
            "hash": "a" * 64,
            "filename": "dopilot_demo-0.1.0-py3-none-any.whl",
            "fetch_path": "/api/v1/artifacts/python_wheel/" + "a" * 64 + "/wheel",
        }
    payload = {
        "shell_command": shell_command,
        "artifact": artifact,
        "env": env or {},
        "working_dir": working_dir,
        "task_type": "python_wheel",
    }
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.run,
        agent_id=AGENT_ID,
        task_id=task_id,
        execution_id=execution_id,
        task_type="python_wheel",
        payload=payload,
        created_at="t",
    )


def _stop_cmd(intent: StopIntent, *, execution_id="w1", task_id="t1") -> AgentCommand:
    # Mirrors the server: stop commands carry an EMPTY payload, so task_type
    # defaults to "scrapy" on the wire — the agent must branch on local state.
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.stop,
        agent_id=AGENT_ID,
        task_id=task_id,
        execution_id=execution_id,
        intent=intent,
        created_at="t",
    )


async def _events(fake) -> list[AgentEvent]:
    entries = await fake.entries(EVENT_STREAM)
    return [from_stream_entry(AgentEvent, f) for _id, f in entries]


async def _event_types(fake) -> list[AgentEventType]:
    return [e.type for e in await _events(fake)]


async def _settle(consumer, timeout: float = 10.0) -> None:
    """Await the tracked background wait tasks (terminal-event emitters)."""
    for task in list(consumer._wait_tasks.values()):
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


# --------------------------------------------------------------------------- #
# Success / failure / validation
# --------------------------------------------------------------------------- #
async def test_wheel_run_success_emits_finished_and_merges_log(workdir, fake_redis):
    fake = fake_redis()
    store, _r, wheel_runner, cache, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    cmd = _wheel_cmd(shell_command="echo OUT; echo ERR 1>&2")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()
    await _settle(consumer)

    state = store.read("w1")
    assert state.phase == "done" and state.result == "finished"
    assert state.exit_code == 0
    assert state.runner_type == "python_wheel"
    assert len(cache.calls) == 1
    assert await _event_types(fake) == [
        AgentEventType.accepted,
        AgentEventType.running,
        AgentEventType.finished,
    ]
    # stdout + stderr merged into one local job.log.
    merged = Path(state.log_path).read_text(encoding="utf-8")
    assert "OUT" in merged and "ERR" in merged


async def test_wheel_run_nonzero_exit_emits_failed_with_code(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="exit 7")))
    await consumer.drain_once()
    await _settle(consumer)

    state = store.read("w1")
    assert state.result == "failed" and state.exit_code == 7
    events = await _events(fake)
    assert events[-1].type is AgentEventType.failed
    assert events[-1].exit_code == 7


async def test_wheel_run_pythonpath_and_unbuffered_injected(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, cache, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    cmd = _wheel_cmd(
        shell_command='echo "PP=$PYTHONPATH"; echo "BUF=$PYTHONUNBUFFERED"'
    )
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()
    await _settle(consumer)

    merged = Path(store.read("w1").log_path).read_text(encoding="utf-8")
    assert str(workdir / "site") in merged  # install site on PYTHONPATH
    assert "BUF=1" in merged


async def test_wheel_run_working_dir_escape_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    cmd = _wheel_cmd(shell_command="echo hi", working_dir="../escape")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()
    await _settle(consumer)

    state = store.read("w1")
    assert state.result == "failed" and state.error_code == "working_dir_invalid"
    assert (await _events(fake))[-1].type is AgentEventType.failed


async def test_wheel_run_relative_working_dir_is_cwd(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    cmd = _wheel_cmd(shell_command="pwd", working_dir="sub/dir")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()
    await _settle(consumer)

    state = store.read("w1")
    assert state.result == "finished"
    merged = Path(state.log_path).read_text(encoding="utf-8")
    assert str((Path(state.workspace_path) / "sub" / "dir").resolve()) in merged


async def test_wheel_run_empty_command_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, cache, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="   ")))
    await consumer.drain_once()

    state = store.read("w1")
    assert state.result == "failed" and state.error_code == "command_invalid"
    assert len(cache.calls) == 0  # never tried to install
    events = await _events(fake)
    assert [e.type for e in events] == [
        AgentEventType.accepted,
        AgentEventType.failed,
    ]
    assert events[-1].error_detail.get("missing") == "shell_command"


async def test_wheel_run_missing_artifact_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, cache, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    cmd = _wheel_cmd(artifact={"filename": "x.whl"})  # no hash/sha256
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()

    state = store.read("w1")
    assert state.result == "failed" and state.error_code == "command_invalid"
    assert len(cache.calls) == 0
    assert (await _events(fake))[-1].error_detail.get("missing") == "artifact"


async def test_wheel_run_install_error_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    cache = FakeWheelCache(workdir / "site")
    cache.error = WheelCacheError("pip install failed", detail={"returncode": 1})
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake, wheel_cache=cache)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd()))
    await consumer.drain_once()

    state = store.read("w1")
    assert state.result == "failed" and state.error_code == "wheel_install_error"
    events = await _events(fake)
    assert events[-1].type is AgentEventType.failed
    assert events[-1].error_detail.get("returncode") == 1


async def test_wheel_runner_unavailable_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    client = ScrapydClient(
        base_url="http://scrapyd.test", transport=scrapyd.transport()
    )
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client, store=store, logs_dir=scrapyd_logs_dir(workdir)
    )
    publisher = EventPublisher(
        redis=fake, agent_id=AGENT_ID, runner=runner, store=store
    )
    # No wheel runner/cache wired (e.g. a scrapy-only build of the agent).
    consumer = CommandConsumer(
        redis=fake, agent_id=AGENT_ID, runner=runner, store=store,
        events=publisher, pending_idle_ms=0,
    )
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd()))
    await consumer.drain_once()

    assert store.read("w1").error_code == "wheel_runner_unavailable"


# --------------------------------------------------------------------------- #
# Idempotency / dispatch preservation
# --------------------------------------------------------------------------- #
async def test_wheel_duplicate_run_does_not_double_start(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, cache, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    cmd = _wheel_cmd(shell_command="sleep 5")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await fake.xadd(STREAM, to_stream_entry(cmd))  # re-delivered same execution_id
    await consumer.drain_once()

    # Installed/started exactly once; the dup re-emits (no second accepted).
    assert len(cache.calls) == 1
    types = await _event_types(fake)
    assert types.count(AgentEventType.accepted) == 1

    # cleanup: cancel the long sleep so the test doesn't leak the subprocess.
    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    await _settle(consumer)


async def test_scrapy_run_still_works_with_wheel_runner_wired(workdir, fake_redis):
    """The narrow wheel branch must not change the Scrapy run path."""
    fake = fake_redis()
    store, _r, _wr, _c, consumer, scrapyd = _build(workdir, fake)
    await consumer.setup()

    scrapy_cmd = AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.run,
        agent_id=AGENT_ID,
        task_id="t1",
        execution_id="s1",
        task_type="scrapy",
        payload={"command": "scrapy crawl phase1", "artifact": {"project": "demo"}},
        created_at="t",
    )
    await fake.xadd(STREAM, to_stream_entry(scrapy_cmd))
    await consumer.drain_once()

    # Went through the Scrapy path (scheduled on local scrapyd), not the wheel one.
    assert scrapyd._counter == 1
    state = store.read("s1")
    assert state.runner_type == "scrapy" and state.scrapyd_job_id
    assert await _event_types(fake) == [
        AgentEventType.accepted,
        AgentEventType.running,
    ]


# --------------------------------------------------------------------------- #
# Cancellation / reclaim
# --------------------------------------------------------------------------- #
async def test_wheel_cancel_terminates_group_and_emits_canceled(workdir, fake_redis):
    fake = fake_redis()
    store, _r, wheel_runner, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="sleep 30")))
    await consumer.drain_once()
    pgid = store.read("w1").pgid
    assert pgid and _group_alive(pgid)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    await _settle(consumer)

    assert store.read("w1").result == "canceled"
    assert AgentEventType.canceled in await _event_types(fake)
    assert not _group_alive(pgid)


async def test_wheel_cancel_sigkill_when_sigterm_ignored(workdir, fake_redis):
    fake = fake_redis()
    # tiny grace so the SIGKILL escalation path is fast.
    store, _r, wheel_runner, _c, consumer, _s = _build(
        workdir, fake, grace_seconds=0.2
    )
    await consumer.setup()

    # trap '' TERM ignores SIGTERM -> only SIGKILL after the grace stops it.
    cmd = _wheel_cmd(shell_command="trap '' TERM; sleep 30")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()
    pgid = store.read("w1").pgid
    assert _group_alive(pgid)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    await _settle(consumer)

    assert store.read("w1").result == "canceled"
    assert not _group_alive(pgid)


async def test_wheel_reclaim_kills_but_stays_lost(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="sleep 30")))
    await consumer.drain_once()
    pgid = store.read("w1").pgid

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)
    await _settle(consumer)

    assert store.read("w1").result == "lost"
    assert AgentEventType.canceled not in await _event_types(fake)
    assert not _group_alive(pgid)


# --------------------------------------------------------------------------- #
# Recovery / cleanup
# --------------------------------------------------------------------------- #
async def test_wheel_started_orphan_recovered_as_lost(workdir, fake_redis):
    fake = fake_redis()
    store, _r, wheel_runner, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    # A real orphan process group left by a "previous" agent process.
    proc = subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-c", "sleep 30"], start_new_session=True
    )
    pgid = os.getpgid(proc.pid)
    reserved = store.create_reserved(
        task_id="t1", execution_id="w1", runner_type="python_wheel"
    )
    assert reserved is not None
    store.promote_started_wheel(
        "w1", pid=proc.pid, pgid=pgid,
        workspace_path=str(workdir / "ws"), install_path=str(workdir / "site"),
        log_path=str(workdir / "ws" / "job.log"),
    )

    recovered = await consumer.recover_wheel_orphans()
    assert recovered == 1
    state = store.read("w1")
    assert state.phase == "done" and state.result == "lost"
    assert state.lost_reason == "runner_recovered_unknown"
    events = await _events(fake)
    assert events[-1].type is AgentEventType.lost
    # orphan group was killed; reap to avoid a zombie.
    with contextlib.suppress(ProcessLookupError):
        proc.wait(timeout=5)
    assert not _group_alive(pgid)

    # A re-delivered run for the same execution must NOT restart it.
    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="echo x")))
    await consumer.drain_once()
    assert store.read("w1").result == "lost"


async def test_aclose_terminates_running_process_group(workdir):
    """aclose() must not leak a started shell process group on shutdown."""
    runner = PythonWheelRunner(
        workspace_root=wheel_workspace_dir(workdir), grace_seconds=0.2
    )
    started = await runner.start(
        execution_id="leak",
        task_id="t",
        shell_command="sleep 30",
        install_path=str(workdir),
    )
    pgid = started.pgid
    assert _group_alive(pgid)

    await runner.aclose()

    assert not _group_alive(pgid)
    # Bookkeeping is dropped so a reused runner keeps no stale handles.
    assert runner._procs == {}
    assert runner._pgids == {}
    assert runner._reapers == {}
    assert runner._logs == {}


async def test_consumer_stop_terminates_running_wheel(workdir, fake_redis):
    """The app shutdown path (CommandConsumer.stop) must kill live wheel jobs."""
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake, grace_seconds=0.2)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="sleep 30")))
    await consumer.drain_once()
    pgid = store.read("w1").pgid
    assert pgid and _group_alive(pgid)

    await consumer.stop()

    # Shutdown killed the group without emitting an extra terminal event.
    assert not _group_alive(pgid)
    assert AgentEventType.canceled not in await _event_types(fake)
    assert AgentEventType.finished not in await _event_types(fake)


async def test_wheel_cleanup_removes_state_and_workspace(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_wheel_cmd(shell_command="echo hi")))
    await consumer.drain_once()
    await _settle(consumer)
    state = store.read("w1")
    workspace = Path(state.workspace_path)
    assert workspace.is_dir() and Path(state.log_path).is_file()

    cleanup = AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.cleanup_logs,
        agent_id=AGENT_ID,
        task_id="t1",
        execution_id="w1",
        created_at="t",
    )
    await fake.xadd(STREAM, to_stream_entry(cleanup))
    await consumer.drain_once(claim_pending=False)

    assert store.read("w1") is None
    assert not workspace.exists()


# --------------------------------------------------------------------------- #
# Log publishing of the merged wheel log
# --------------------------------------------------------------------------- #
async def test_log_publisher_publishes_merged_wheel_log_and_eof(workdir, fake_redis):
    fake = fake_redis()
    store, _r, _wr, _c, consumer, _s = _build(workdir, fake)
    await consumer.setup()

    await fake.xadd(
        STREAM, to_stream_entry(_wheel_cmd(shell_command="echo line1; echo line2"))
    )
    await consumer.drain_once()
    await _settle(consumer)

    publisher = LogPublisher(
        redis=fake,
        agent_id=AGENT_ID,
        store=store,
        cursor_dir=str(store.dir / "logpos"),
    )
    await publisher.publish_attempt("w1")

    entries = await fake.entries(LOG_STREAM)
    logs = [from_stream_entry(AgentLogEvent, f) for _id, f in entries]
    assert logs, "expected at least one published log increment"
    # all on the single shared "log" stream; an eof marker closes it.
    body = b"".join(
        base64.b64decode(e.content_b64) for e in logs if not e.eof
    ).decode("utf-8")
    assert "line1" in body and "line2" in body
    assert any(e.eof for e in logs)


# --------------------------------------------------------------------------- #
# Real PythonWheelCache install (offline, demo wheel pre-placed)
# --------------------------------------------------------------------------- #
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preplace_demo_wheel(cache_root: Path) -> tuple[str, str]:
    """Drop the demo wheel into the cache layout so ensure() skips the fetch."""
    sha = _sha256(DEMO_WHEEL)
    sha_dir = cache_root / "python_wheel" / sha
    sha_dir.mkdir(parents=True, exist_ok=True)
    (sha_dir / DEMO_WHEEL.name).write_bytes(DEMO_WHEEL.read_bytes())
    return sha, DEMO_WHEEL.name


@pytest.mark.skipif(not DEMO_WHEEL.is_file(), reason="demo wheel fixture missing")
async def test_wheel_cache_install_argv_uses_no_deps_target(workdir, monkeypatch):
    captured: dict = {}

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = list(argv)
        # write a marker into the --target site so the install "succeeds".
        target = argv[argv.index("--target") + 1]
        Path(target).mkdir(parents=True, exist_ok=True)
        (Path(target) / "main.py").write_text("x", encoding="utf-8")

        class _Proc:
            returncode = 0

            async def communicate(self):
                return (b"ok", b"")

        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    sha, _name = _preplace_demo_wheel(workdir)
    cache = PythonWheelCache(
        root_dir=workdir, server_url="http://server.test"
    )
    site = await cache.ensure(
        {"hash": sha, "filename": DEMO_WHEEL.name}, execution_id="w1"
    )

    argv = captured["argv"]
    assert argv[0] == sys.executable
    assert argv[1:5] == ["-m", "pip", "install", "--no-deps"]
    assert "--target" in argv and site in argv
    assert argv[-1].endswith(".whl")


@pytest.mark.skipif(not DEMO_WHEEL.is_file(), reason="demo wheel fixture missing")
async def test_wheel_cache_real_install_idempotent_by_sha(workdir):
    sha, _name = _preplace_demo_wheel(workdir)

    install_count = {"n": 0}

    class CountingCache(PythonWheelCache):
        async def _pip_install(self, wheel_path, site, *, sha256):
            install_count["n"] += 1
            await super()._pip_install(wheel_path, site, sha256=sha256)

    cache = CountingCache(root_dir=workdir, server_url="http://server.test")
    artifact = {"hash": sha, "filename": DEMO_WHEEL.name}

    site1 = await cache.ensure(artifact, execution_id="w1")
    site2 = await cache.ensure(artifact, execution_id="w2")  # redelivered

    assert site1 == site2
    assert install_count["n"] == 1  # installed once per sha256
    assert (Path(site1) / "main.py").is_file()
    assert (workdir / "python_wheel" / sha / ".ready").is_file()


# --------------------------------------------------------------------------- #
# End-to-end offline smoke: demo wheel + local HTTP server
# --------------------------------------------------------------------------- #
class _HeadersHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"headers": {"Host": "local"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # silence test output
        pass


@pytest.mark.skipif(not DEMO_WHEEL.is_file(), reason="demo wheel fixture missing")
async def test_demo_wheel_offline_end_to_end(workdir, fake_redis):
    """server->agent->log smoke: real install + run of the demo wheel offline."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _HeadersHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        sha, name = _preplace_demo_wheel(workdir)
        fake = fake_redis()
        cache = PythonWheelCache(root_dir=workdir, server_url="http://server.test")
        store, _r, _wr, _c, consumer, _s = _build(
            workdir, fake, wheel_cache=cache, grace_seconds=2.0
        )
        await consumer.setup()

        # The demo command is ``python -m main``; this box only ships
        # ``python3``, so the smoke uses the running interpreter to stay
        # portable while exercising the same ``-m main`` module form.
        cmd = _wheel_cmd(
            shell_command=f"{shlex.quote(sys.executable)} -m main",
            artifact={
                "hash": sha,
                "filename": name,
                "fetch_path": f"/api/v1/artifacts/python_wheel/{sha}/wheel",
            },
            env={"DOPILOT_DEMO_URL": f"http://127.0.0.1:{port}/headers"},
        )
        await fake.xadd(STREAM, to_stream_entry(cmd))
        await consumer.drain_once()
        await _settle(consumer, timeout=30.0)

        state = store.read("w1")
        assert state.result == "finished" and state.exit_code == 0
        merged = Path(state.log_path).read_text(encoding="utf-8")
        assert "response headers" in merged
        assert await _event_types(fake) == [
            AgentEventType.accepted,
            AgentEventType.running,
            AgentEventType.finished,
        ]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _group_alive(pgid: int) -> bool:
    """True if the process group still has at least one live member."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
