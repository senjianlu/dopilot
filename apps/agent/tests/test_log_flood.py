"""Log-flood guard: agent watchdog, escalation, terminal stats and backpressure.

TC-01 / TC-01b / TC-01c / TC-01h / TC-02 / TC-02b / TC-06 / TC-08 / TC-09 /
TC-01f(a)(c).
"""

from __future__ import annotations

import os
import signal
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dopilot_agent.deps import scrapyd_logs_dir, state_dir
from dopilot_agent.logcap import SETTING_NAME as LOG_CAP_SETTING
from dopilot_agent.redis.commands import CommandConsumer
from dopilot_agent.redis.events import EventPublisher
from dopilot_agent.redis.logs import LogPublisher
from dopilot_agent.runners.scrapyd import ScrapyRunner
from dopilot_agent.scrapyd.client import ScrapydClient
from dopilot_agent.scrapyd.process import ScrapydProcess
from dopilot_agent.state.store import StateStore
from dopilot_protocol import (
    COMMAND_GROUP,
    EVENT_STREAM,
    LOG_STREAM,
    AgentCommand,
    AgentCommandType,
    AgentEvent,
    AgentEventType,
    AgentLogEvent,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)

from .conftest import FakeScrapyd

AGENT_ID = "agent-x"
STREAM = command_stream(AGENT_ID)
CAP = 4096
SCRAPYD_PID = 4242

STATS_TAIL = (
    "[scrapy.statscollectors] INFO: Dumping Scrapy stats:\n"
    "{'finish_reason': 'finished',\n 'log_count/ERROR': 91}\n"
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 21, 11, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _fake_proc(root: Path, pid: int, argv: list[str], ppid: int) -> None:
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "stat").write_text(f"{pid} (python) S {ppid} 1 1 0 -1", encoding="utf-8")


def _build(
    workdir: Path,
    fake_scrapyd: FakeScrapyd,
    redis,
    *,
    cap: int = CAP,
    kill_after: int = 30,
    scrapyd_pid=lambda: SCRAPYD_PID,
    proc_root: Path | None = None,
    clock: Clock | None = None,
    rate: int = 0,
):
    client = ScrapydClient(base_url="http://scrapyd.test", transport=fake_scrapyd.transport())
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client, store=store, logs_dir=scrapyd_logs_dir(workdir),
        max_job_log_bytes=cap,
    )
    publisher = EventPublisher(redis=redis, agent_id=AGENT_ID, runner=runner, store=store)
    consumer = CommandConsumer(
        redis=redis, agent_id=AGENT_ID, runner=runner, store=store, events=publisher,
        pending_idle_ms=0, max_job_log_bytes=cap, log_flood_kill_after_seconds=kill_after,
        scrapyd_pid=scrapyd_pid, proc_root=proc_root or (workdir / "proc"),
        now=clock or Clock(),
    )
    log_publisher = LogPublisher(
        redis=redis, agent_id=AGENT_ID, store=store, cursor_dir=str(workdir / "logpos"),
        max_job_log_bytes=cap, rate_bytes_per_second=rate,
        on_eof=consumer.on_execution_eof,
    )
    consumer.set_log_publisher(log_publisher)
    return store, runner, consumer, log_publisher


def _run_cmd(execution_id="a1", task_id="e1") -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex, type=AgentCommandType.run, agent_id=AGENT_ID,
        task_id=task_id, execution_id=execution_id,
        payload={"command": "scrapy crawl phase1", "artifact": {"project": "demo"}},
        created_at="t",
    )


def _stop_logs_cmd(execution_id="a1", task_id="e1") -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex, type=AgentCommandType.stop_logs, agent_id=AGENT_ID,
        task_id=task_id, execution_id=execution_id, created_at="t",
    )


async def _events(fake) -> list[AgentEvent]:
    return [from_stream_entry(AgentEvent, f) for _id, f in await fake.entries(EVENT_STREAM)]


async def _log_events(fake) -> list[AgentLogEvent]:
    return [from_stream_entry(AgentLogEvent, f) for _id, f in await fake.entries(LOG_STREAM)]


async def _start(workdir, scrapyd, fake, **kw):
    store, runner, consumer, pub = _build(workdir, scrapyd, fake, **kw)
    await consumer.setup()
    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    state = store.read("a1")
    log = Path(state.log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    return store, runner, consumer, pub, state, log


def _marker_len(cap: int) -> int:
    return len(f"\n[dopilot:job-log-truncated max_bytes={cap} reason=size-cap]\n")


# --- TC-01: cap reached -> cancel -> failed/log_flood -------------------------


async def test_flood_cancels_then_reports_failed_log_flood(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _r, consumer, _pub, state, log = await _start(workdir, scrapyd, fake)

    log.write_bytes(b"x" * (CAP + 1))
    await consumer.reconcile_started_attempts()
    st = store.read("a1")
    assert st.log_flood is True and st.log_flood_bytes >= CAP + 1
    assert st.log_flood_escalation == "term"
    assert scrapyd.cancels and scrapyd.cancels[0]["job"] == state.scrapyd_job_id
    assert scrapyd.cancels[0]["signal"] is None  # plain TERM cancel first

    # FakeScrapyd moves the job to finished on cancel -> the terminal resolves in
    # the same tick (a real scrapyd may need one more tick; both paths end here).
    await consumer.reconcile_started_attempts()
    st = store.read("a1")
    assert st.phase == "done" and st.result == "failed" and st.error_code == "log_flood"
    ev = (await _events(fake))[-1]
    assert ev.type is AgentEventType.failed and ev.error_code == "log_flood"
    assert ev.error_detail["log_bytes"] >= CAP + 1 and ev.error_detail["cap"] == CAP
    assert ev.log_bytes >= CAP + 1
    # Even a cap+1 flood is cut to EXACTLY the first cap bytes + one marker.
    marker = f"\n[dopilot:job-log-truncated max_bytes={CAP} reason=size-cap]\n".encode()
    assert log.read_bytes() == b"x" * CAP + marker
    assert log.stat().st_size == CAP + len(marker)
    # idempotent: another pass leaves exactly one marker
    await consumer.reconcile_started_attempts()
    assert log.read_bytes() == b"x" * CAP + marker


# --- TC-02: below the cap nothing happens ---------------------------------------


async def test_below_cap_is_untouched_and_finishes_normally(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _r, consumer, _pub, state, log = await _start(workdir, scrapyd, fake)
    log.write_bytes(b"x" * (CAP - 1))
    await consumer.reconcile_started_attempts()
    assert scrapyd.cancels == []
    assert store.read("a1").log_flood is False
    scrapyd.move_to_finished(state.scrapyd_job_id)
    await consumer.reconcile_started_attempts()
    st = store.read("a1")
    assert st.result == "finished" and st.error_code is None
    assert log.stat().st_size == CAP - 1


# --- TC-02b: cap 0 = disabled everywhere ----------------------------------------


async def test_cap_zero_disables_watchdog_publisher_and_injection(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _r, consumer, pub, state, log = await _start(workdir, scrapyd, fake, cap=0)
    assert LOG_CAP_SETTING not in scrapyd.schedules[0]["settings"]
    big = b"y" * (100 * 1024)
    log.write_bytes(big)
    await consumer.reconcile_started_attempts()
    assert scrapyd.cancels == [] and store.read("a1").log_flood is False
    await pub.publish_once()
    assert sum(e.size_bytes for e in await _log_events(fake)) == len(big)
    assert store.read("a1").log_capped is False


# --- TC-01f(a)(c): injection + no daemon env ------------------------------------


async def test_schedule_injects_cap_setting_next_to_runtime_context(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    await _start(workdir, scrapyd, fake, cap=12345)
    settings = scrapyd.schedules[0]["settings"]
    assert settings[LOG_CAP_SETTING] == "12345"


def test_managed_scrapyd_daemon_gets_no_cap_env(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    class FakePopen:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            self.pid = 1

        def poll(self):
            return None

    monkeypatch.setattr("dopilot_agent.scrapyd.process.subprocess.Popen", FakePopen)
    proc = ScrapydProcess(workdir=tmp_path)
    proc.start()
    env = captured.get("env")
    assert env is None or LOG_CAP_SETTING not in env


# --- TC-01b: escalation TERM -> KILL -> single-PID SIGKILL --------------------------


async def test_escalation_and_disk_bound_when_cancel_is_ignored(
    workdir, fake_redis, monkeypatch
):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    scrapyd.fail_cancel_times = 1
    scrapyd.sticky_running = True
    clock = Clock()
    proc_root = workdir / "proc"
    store, _r, consumer, _pub, state, log = await _start(
        workdir, scrapyd, fake, clock=clock, proc_root=proc_root
    )
    job = state.scrapyd_job_id
    _fake_proc(proc_root, 100, ["python", "-m", "scrapyd.runner", "crawl", "phase1",
                                "-a", f"_job={job}"], SCRAPYD_PID)
    _fake_proc(proc_root, 101, ["python", "-m", "scrapyd.runner", "crawl", "other",
                                "-a", "_job=other-job"], SCRAPYD_PID)
    _fake_proc(proc_root, 102, ["python", "crawl", "-a", f"_job={job}"], 1)  # wrong parent

    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda *a: pytest.fail("killpg must never be used"))

    bound = CAP + _marker_len(CAP)

    def flood(extra: int = 1024 * 1024) -> None:
        with log.open("ab") as fh:
            fh.write(b"z" * extra)

    flood()
    await consumer.reconcile_started_attempts()  # t=0: cancel raised -> warning only
    assert len(scrapyd.cancels) == 1 and store.read("a1").log_flood
    assert log.stat().st_size <= bound  # truncated immediately on first detection

    clock.advance(5)
    flood()
    await consumer.reconcile_started_attempts()  # t=5: TERM again
    assert scrapyd.cancels[-1]["signal"] is None
    assert log.stat().st_size <= bound

    clock.advance(30)
    flood()
    await consumer.reconcile_started_attempts()  # t=35: KILL
    assert scrapyd.cancels[-1]["signal"] == "KILL"
    assert store.read("a1").log_flood_escalation == "kill"
    assert log.stat().st_size <= bound

    clock.advance(35)
    flood()
    await consumer.reconcile_started_attempts()  # t=70: single-PID SIGKILL
    assert kills == [(100, signal.SIGKILL)]
    assert store.read("a1").log_flood_escalation == "pidkill"
    assert log.stat().st_size <= bound

    clock.advance(5)
    flood()
    await consumer.reconcile_started_attempts()  # still running: no second pid kill
    assert kills == [(100, signal.SIGKILL)]
    assert log.stat().st_size <= bound


# --- TC-01c: ambiguous candidates -> never kill ---------------------------------------


async def test_ambiguous_crawler_candidates_are_never_killed(workdir, fake_redis, monkeypatch):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    scrapyd.sticky_running = True
    clock = Clock()
    proc_root = workdir / "proc"
    store, _r, consumer, _pub, state, log = await _start(
        workdir, scrapyd, fake, clock=clock, proc_root=proc_root
    )
    job = state.scrapyd_job_id
    for pid in (200, 201):
        _fake_proc(proc_root, pid, ["python", "crawl", "x", "-a", f"_job={job}"], SCRAPYD_PID)
    kills: list = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
    log.write_bytes(b"x" * (CAP + 10))
    await consumer.reconcile_started_attempts()
    clock.advance(70)
    with log.open("ab") as fh:
        fh.write(b"x" * 50000)
    await consumer.reconcile_started_attempts()
    assert kills == []
    assert scrapyd.cancels[-1]["signal"] == "KILL"  # keeps re-sending cancel
    assert store.read("a1").log_flood_escalation != "pidkill"
    assert log.stat().st_size <= CAP + _marker_len(CAP)


# --- TC-01h: external scrapyd mode -----------------------------------------------------


async def test_external_mode_has_no_pid_kill(workdir, fake_redis, monkeypatch, caplog):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    scrapyd.sticky_running = True
    scrapyd.fail_cancel_times = 100
    clock = Clock()
    proc_root = workdir / "proc"
    store, _r, consumer, _pub, state, log = await _start(
        workdir, scrapyd, fake, clock=clock, proc_root=proc_root, scrapyd_pid=None
    )
    _fake_proc(proc_root, 300, ["python", "crawl", "x", "-a", f"_job={state.scrapyd_job_id}"], 7)
    kills: list = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
    log.write_bytes(b"x" * (CAP + 10))
    await consumer.reconcile_started_attempts()
    clock.advance(70)
    with log.open("ab") as fh:
        fh.write(b"x" * 50000)
    with caplog.at_level("WARNING"):
        await consumer.reconcile_started_attempts()
    assert kills == []
    assert any("external mode" in r.getMessage() for r in caplog.records)
    assert scrapyd.cancels[-1]["signal"] == "KILL"
    assert log.stat().st_size <= CAP + _marker_len(CAP)


# --- TC-06: terminal carries scrapy stats ---------------------------------------------


async def test_terminal_event_carries_scrapy_stats(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _r, consumer, _pub, state, log = await _start(workdir, scrapyd, fake)
    log.write_text("2026 INFO: Scrapy started\n" + STATS_TAIL, encoding="utf-8")
    scrapyd.move_to_finished(state.scrapyd_job_id)
    await consumer.reconcile_started_attempts()
    ev = (await _events(fake))[-1]
    assert ev.type is AgentEventType.finished
    assert ev.error_count == 91 and ev.finish_reason == "finished"
    assert ev.log_bytes == log.stat().st_size
    st = store.read("a1")
    assert (st.error_count, st.finish_reason, st.log_bytes) == (91, "finished", ev.log_bytes)


# --- TC-08: stop_logs backpressure ----------------------------------------------------


async def test_stop_logs_caps_the_publisher(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _r, consumer, pub, state, log = await _start(workdir, scrapyd, fake, cap=1 << 20)
    log.write_bytes(b"a" * 100)
    await pub.publish_once()
    assert sum(e.size_bytes for e in await _log_events(fake)) == 100

    await fake.xadd(STREAM, to_stream_entry(_stop_logs_cmd()))
    await consumer.drain_once()
    assert store.read("a1").log_capped is True
    with log.open("ab") as fh:
        fh.write(b"b" * 100)
    await pub.publish_once()
    assert sum(e.size_bytes for e in await _log_events(fake)) == 100  # no new content


# --- TC-09: undecodable command is ACKed, not a poison message -----------------------------


async def test_bogus_command_is_acked_and_logged(workdir, fake_redis, caplog):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _r, consumer, _pub = _build(workdir, scrapyd, fake)
    await consumer.setup()
    bogus = {b"data": b'{"command_id":"c0","type":"bogus","agent_id":"agent-x",'
                     b'"task_id":"t","execution_id":"x","created_at":"t"}'}
    await fake.xadd(STREAM, bogus)
    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    with caplog.at_level("WARNING"):
        n = await consumer.drain_once()
    assert n == 2
    assert any("undecodable command entry" in r.getMessage() for r in caplog.records)
    assert await fake.pending_count(STREAM, COMMAND_GROUP) == 0
    assert store.read("a1").phase == "started"  # the following run was handled


# --- R-03 regression: a job-id PREFIX collision must never pick another crawler --------


async def test_job_id_prefix_collision_never_kills_other_crawler(
    workdir, fake_redis, monkeypatch
):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    scrapyd.sticky_running = True
    clock = Clock()
    proc_root = workdir / "proc"
    store, _r, consumer, _pub, state, log = await _start(
        workdir, scrapyd, fake, clock=clock, proc_root=proc_root
    )
    job = state.scrapyd_job_id
    # the target crawler already exited; only a crawler whose job id merely
    # STARTS with ours is alive under the same scrapyd
    _fake_proc(proc_root, 400, ["python", "-m", "scrapyd.runner", "crawl", "x",
                                "-a", f"_job={job}2"], SCRAPYD_PID)
    kills: list = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
    log.write_bytes(b"x" * (CAP + 10))
    await consumer.reconcile_started_attempts()
    clock.advance(70)
    with log.open("ab") as fh:
        fh.write(b"x" * 50000)
    await consumer.reconcile_started_attempts()
    assert kills == []
    assert store.read("a1").log_flood_escalation != "pidkill"
    assert log.stat().st_size <= CAP + _marker_len(CAP)
