"""Stop/reclaim as a tick-driven state machine.

Waiting for a process to die inside ``_handle_stop`` is not an option: the
command consumer is serial, so one batch of cancels would freeze every other
execution's heartbeat and flood check for the whole confirmation window. The
intent is persisted instead and driven forward one tick at a time.

Two invariants get most of the attention here:

* Terminal reporting is time-bounded, process reclamation is NOT. When the
  deadline passes with the process still alive we report the terminal (the
  contract says ``canceled`` always arrives) but keep the scrapyd job mapping
  and go on trying -- dropping it would recreate exactly the untrackable orphan
  this machinery exists to prevent.
* ``cancel`` and ``reclaim`` never share an outcome. Once we TERM a job the
  runner marks it canceled locally, so a departed job then *resolves* as
  ``canceled`` -- our own doing. Treating that as authoritative would overwrite
  a reclaim's ``lost``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dopilot_agent.deps import scrapyd_logs_dir, state_dir
from dopilot_agent.redis.commands import CommandConsumer
from dopilot_agent.redis.events import EventPublisher
from dopilot_agent.runners.scrapyd import ScrapyRunner
from dopilot_agent.scrapyd.client import ScrapydClient
from dopilot_agent.state.store import StateStore
from dopilot_protocol import (
    EVENT_STREAM,
    AgentCommand,
    AgentCommandType,
    AgentEvent,
    AgentEventType,
    StopIntent,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)

from .conftest import FakeScrapyd

AGENT_ID = "agent-x"
STREAM = command_stream(AGENT_ID)


class Clock:
    """Hand-cranked clock so deadlines can be crossed without sleeping."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _build(workdir: Path, scrapyd: FakeScrapyd, redis, clock, **kw):
    client = ScrapydClient(
        base_url="http://scrapyd.test", transport=scrapyd.transport()
    )
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client, store=store, logs_dir=scrapyd_logs_dir(workdir)
    )
    publisher = EventPublisher(
        redis=redis, agent_id=AGENT_ID, runner=runner, store=store
    )
    consumer = CommandConsumer(
        redis=redis,
        agent_id=AGENT_ID,
        runner=runner,
        store=store,
        events=publisher,
        pending_idle_ms=0,
        now=clock,
        **kw,
    )
    return store, runner, consumer


def _run_cmd(execution_id="a1", task_id="e1") -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.run,
        agent_id=AGENT_ID,
        task_id=task_id,
        execution_id=execution_id,
        payload={
            "command": "scrapy crawl phase1",
            "artifact": {"project": "demo"},
        },
        created_at="t",
    )


def _stop_cmd(intent: StopIntent, execution_id="a1", task_id="e1") -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.stop,
        agent_id=AGENT_ID,
        task_id=task_id,
        execution_id=execution_id,
        intent=intent,
        created_at="t",
    )


def _cleanup_cmd(execution_id="a1", task_id="e1") -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.cleanup_logs,
        agent_id=AGENT_ID,
        task_id=task_id,
        execution_id=execution_id,
        created_at="t",
    )


async def _event_types(fake) -> list[AgentEventType]:
    entries = await fake.entries(EVENT_STREAM)
    return [from_stream_entry(AgentEvent, f).type for _id, f in entries]


def _signals(scrapyd: FakeScrapyd) -> list[str | None]:
    return [c["signal"] for c in scrapyd.cancels]


async def _start(fake, consumer, scrapyd, store=None):
    await consumer.setup()
    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    assert len(scrapyd.running) == 1
    if store is not None:
        _write_log(store)
    return scrapyd.running[0]["id"]


def _write_log(store, execution_id="a1", *, workspace=False):
    """Give the attempt real artifacts so cleanup can be checked on disk.

    Returns ``(log_path, workspace_path)``; ``workspace_path`` is ``None``
    unless asked for (a Scrapy attempt normally has none -- only wheel runs own
    a per-execution workspace -- so it is opt-in).
    """
    state = store.read(execution_id)
    log_path = Path(state.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("2026-09-16 [scrapy] INFO: crawling\n", encoding="utf-8")

    ws_path = None
    if workspace:
        ws_path = log_path.parent / f"ws-{execution_id}"
        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "job.log").write_text("merged\n", encoding="utf-8")
        state.workspace_path = str(ws_path)
        store.write(state)
    return log_path, ws_path


def _assert_not_cleaned(store, paths, execution_id="a1") -> None:
    """The state AND every artifact must survive."""
    log_path, ws_path = paths if isinstance(paths, tuple) else (paths, None)
    assert store.read(execution_id) is not None
    assert log_path.exists()
    if ws_path is not None:
        assert ws_path.exists()


def _assert_cleaned(store, paths, execution_id="a1") -> None:
    """Cleanup really happened: state gone, log and workspace actually deleted."""
    log_path, ws_path = paths if isinstance(paths, tuple) else (paths, None)
    assert store.read(execution_id) is None
    assert not log_path.exists()
    if ws_path is not None:
        assert not ws_path.exists()


async def test_cancel_escalates_to_kill_then_confirms(workdir, fake_redis):
    # TC-17: TERM ignored -> KILL after the grace window -> terminal only once
    # the job is confirmed gone. And _handle_stop must not block: right after it
    # returns the job is still listed.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=120,
    )
    job = await _start(fake, consumer, scrapyd)
    scrapyd.sticky_running = True  # TERM will not kill it

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    # returned immediately: no waiting, job still alive, intent on disk
    assert len(scrapyd.running) == 1
    assert store.read("a1").stop_requested_at is not None
    assert store.read("a1").stop_escalation == "term"
    assert _signals(scrapyd) == [None]
    assert AgentEventType.canceled not in await _event_types(fake)

    # before the grace window: no escalation
    clock.advance(5)
    await consumer.reconcile_started_attempts()
    assert _signals(scrapyd) == [None]

    # past it: one KILL
    clock.advance(10)
    await consumer.reconcile_started_attempts()
    assert _signals(scrapyd) == [None, "KILL"]
    assert store.read("a1").stop_escalation == "kill"
    assert AgentEventType.canceled not in await _event_types(fake)

    # the KILL lands
    scrapyd.sticky_running = False
    scrapyd.move_to_finished(job)
    clock.advance(5)
    await consumer.reconcile_started_attempts()

    assert (await _event_types(fake)).count(AgentEventType.canceled) == 1
    state = store.read("a1")
    assert state.result == "canceled"
    assert state.kill_pending is False
    assert state.terminal_pending is False


async def test_cancel_that_dies_on_term_never_sends_kill(workdir, fake_redis):
    # TC-18
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_kill_after_seconds=10
    )
    await _start(fake, consumer, scrapyd)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    clock.advance(60)  # well past the grace window
    await consumer.reconcile_started_attempts()

    assert _signals(scrapyd) == [None]  # TERM only
    assert store.read("a1").result == "canceled"


async def test_deadline_reports_terminal_but_keeps_reclaiming(workdir, fake_redis):
    # TC-19 + TC-37: the process outlives the deadline. The terminal still
    # arrives on time, but the job mapping stays and KILLs keep going out.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=60,
        kill_retry_interval_seconds=30,
    )
    await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    # a cleanup request arrives BEFORE the deadline and must stay parked
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)
    assert store.read("a1").cleanup_pending is True

    clock.advance(15)
    await consumer.reconcile_started_attempts()  # KILL
    clock.advance(60)
    await consumer.reconcile_started_attempts()  # deadline

    assert (await _event_types(fake)).count(AgentEventType.canceled) == 1
    state = store.read("a1")
    assert state.result == "canceled"
    assert state.kill_pending is True  # reclamation is NOT finished
    assert state.scrapyd_job_id  # mapping deliberately retained
    assert state.terminal_pending is False
    assert state.cleanup_pending is True
    _assert_not_cleaned(store, paths)  # the log survives too

    # retries continue. The first post-deadline pass fires immediately (no
    # previous attempt to pace against), then the interval applies.
    await consumer.reconcile_started_attempts()
    assert _signals(scrapyd)[-1] == "KILL"
    before = len(scrapyd.cancels)
    await consumer.reconcile_started_attempts()  # too soon
    assert len(scrapyd.cancels) == before
    clock.advance(31)
    await consumer.reconcile_started_attempts()
    assert _signals(scrapyd)[-1] == "KILL"
    assert len(scrapyd.cancels) == before + 1
    _assert_not_cleaned(store, paths)

    # the process finally dies: reclamation closes and the parked cleanup runs
    scrapyd.sticky_running = False
    scrapyd.running.clear()
    await consumer.reconcile_started_attempts()
    _assert_cleaned(store, paths)


async def test_reclaim_stays_lost_even_when_status_says_canceled(
    workdir, fake_redis
):
    # TC-24 + TC-39: after TERM the runner's own mark_canceled makes a departed
    # job resolve as ``canceled``. Reclaim must ignore that and stay lost.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, runner, consumer = _build(workdir, scrapyd, fake, clock)
    await _start(fake, consumer, scrapyd)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)
    await consumer.reconcile_started_attempts()

    # the poisoned signal really is present...
    assert store.read("a1").canceled is True
    # ...and was not allowed to become a terminal event
    types = await _event_types(fake)
    assert AgentEventType.canceled not in types
    assert store.read("a1").result == "lost"


async def test_reclaim_with_a_real_terminal_overrides_without_signalling(
    workdir, fake_redis
):
    # TC-25: a terminal observed BEFORE any signal is trustworthy, so reclaim
    # reports it instead of entering the machine.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    job = await _start(fake, consumer, scrapyd)
    scrapyd.move_to_finished(job)  # it finished on its own

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)

    assert scrapyd.cancels == []  # no signal at all
    assert AgentEventType.finished in await _event_types(fake)
    assert store.read("a1").stop_requested_at is None


async def test_first_term_failure_keeps_the_intent_and_retries(
    workdir, fake_redis
):
    # TC-21 + TC-22: the command is XACKed even when the handler raises, so an
    # intent that never reached disk is lost forever. It must be written before
    # the first network call, and escalation must not advance on failure.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    await _start(fake, consumer, scrapyd)
    scrapyd.fail_cancel_times = 1  # first TERM blows up

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)

    state = store.read("a1")
    assert state.stop_requested_at is not None  # intent survived
    assert state.stop_escalation is None  # TERM did NOT succeed
    assert len(scrapyd.running) == 1

    await consumer.reconcile_started_attempts()  # retry: TERM lands this tick
    assert store.read("a1").stop_escalation == "term"
    # liveness is probed before signalling, so the exit is observed next tick
    await consumer.reconcile_started_attempts()
    assert store.read("a1").result == "canceled"


async def test_unreachable_scrapyd_neither_confirms_nor_escalates(
    workdir, fake_redis
):
    # TC-29 + TC-45: an unreachable scrapyd is "cannot tell", never "it is gone".
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=600,
    )
    await _start(fake, consumer, scrapyd)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    scrapyd.fail_listjobs = True

    clock.advance(20)
    await consumer.reconcile_started_attempts()
    state = store.read("a1")
    assert state.phase == "started"  # not finalized
    assert state.result is None
    assert AgentEventType.canceled not in await _event_types(fake)

    # recovery -> normal confirmation
    scrapyd.fail_listjobs = False
    scrapyd.sticky_running = False
    scrapyd.move_to_finished(scrapyd.running[0]["id"])
    await consumer.reconcile_started_attempts()
    assert store.read("a1").result == "canceled"


@pytest.mark.parametrize("intent", [StopIntent.cancel, StopIntent.reclaim])
async def test_persistent_unknown_still_hits_the_deadline(
    workdir, fake_redis, intent
):
    # TC-30 + TC-38: the deadline check runs BEFORE the liveness probe, so a
    # permanently unreachable scrapyd cannot defer the terminal forever. What it
    # must NOT do is close the reclamation: while we cannot see the job, the
    # mapping and the parked cleanup both stay put.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_confirm_timeout_seconds=60
    )
    await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(intent)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)
    assert store.read("a1").cleanup_pending is True

    scrapyd.fail_listjobs = True
    clock.advance(120)
    await consumer.reconcile_started_attempts()  # deadline fires

    state = store.read("a1")
    types = await _event_types(fake)
    if intent is StopIntent.cancel:
        assert state.result == "canceled"
        assert types.count(AgentEventType.canceled) == 1
    else:
        assert state.result == "lost"
        assert AgentEventType.canceled not in types
    assert state.kill_pending is True

    # several more ticks, still blind: nothing is cleaned, nothing is decided
    for _ in range(3):
        clock.advance(90)
        await consumer.reconcile_started_attempts()
        _assert_not_cleaned(store, paths)
        assert store.read("a1").kill_pending is True
        assert store.read("a1").cleanup_pending is True

    # scrapyd comes back and the job is gone -> reclamation closes, cleanup runs
    scrapyd.fail_listjobs = False
    scrapyd.sticky_running = False
    scrapyd.running.clear()
    await consumer.reconcile_started_attempts()
    _assert_cleaned(store, paths)


@pytest.mark.parametrize("intent", [StopIntent.cancel, StopIntent.reclaim])
async def test_cleanup_during_stop_is_deferred_not_dropped(
    workdir, fake_redis, intent
):
    # TC-26: cleanup_logs would delete the state (and the scrapyd job mapping)
    # out from under the machine. It is parked instead and run after
    # confirmation. Both intents matter: a reclaim is exactly the case where the
    # server's own drain window fires a cleanup while we are still killing.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_kill_after_seconds=10
    )
    job = await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(intent)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)

    _assert_not_cleaned(store, paths)  # NOT deleted
    assert store.read("a1").cleanup_pending is True

    clock.advance(15)
    await consumer.reconcile_started_attempts()  # KILL goes out
    assert _signals(scrapyd)[-1] == "KILL"
    _assert_not_cleaned(store, paths)

    scrapyd.sticky_running = False
    scrapyd.move_to_finished(job)
    await consumer.reconcile_started_attempts()

    _assert_cleaned(store, paths)  # cleaned only now
    types = await _event_types(fake)
    if intent is StopIntent.cancel:
        assert types.count(AgentEventType.canceled) == 1
    else:
        assert AgentEventType.canceled not in types


async def test_cleanup_after_terminal_is_deferred_until_the_process_dies(
    workdir, fake_redis
):
    # TC-42: for a cancel, cleanup_logs normally arrives AFTER the terminal (the
    # server starts its drain window at finished_at), i.e. while the state is
    # done + kill_pending. Cleaning then would drop the mapping we still need to
    # finish killing the process.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_confirm_timeout_seconds=60
    )
    await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    clock.advance(120)
    await consumer.reconcile_started_attempts()  # deadline -> terminal
    assert store.read("a1").kill_pending is True
    assert store.read("a1").cleanup_pending is False
    _assert_not_cleaned(store, paths)

    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)
    assert store.read("a1").cleanup_pending is True
    _assert_not_cleaned(store, paths)  # still alive: the process has not died

    # a few more reclamation ticks change nothing on disk
    for _ in range(2):
        clock.advance(70)
        await consumer.reconcile_started_attempts()
        _assert_not_cleaned(store, paths)

    scrapyd.sticky_running = False
    scrapyd.running.clear()
    await consumer.reconcile_started_attempts()
    _assert_cleaned(store, paths)  # log AND workspace gone


async def test_cancel_without_state_still_reports_canceled(workdir, fake_redis):
    # TC-27 + TC-40: cancelling something that never started (or whose state is
    # already gone) must still emit the terminal -- that event is the only thing
    # that converges such a task.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once()

    assert AgentEventType.canceled in await _event_types(fake)
    assert store.read("a1") is None


async def test_reclaim_without_state_is_ignored(workdir, fake_redis):
    # TC-28: the mirror image -- reclaim has nothing to reclaim and must stay
    # silent rather than manufacture a terminal.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    _s, _r, consumer = _build(workdir, scrapyd, fake, clock)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once()

    assert await _event_types(fake) == []


async def test_cancel_on_a_finished_attempt_reports_without_reviving_it(
    workdir, fake_redis
):
    # TC-40: the attempt finished locally and was marked done; a cancel arriving
    # now must report the terminal without pushing the phase back to started.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    job = await _start(fake, consumer, scrapyd)
    scrapyd.move_to_finished(job)
    await consumer.reconcile_started_attempts()  # natural finish -> done
    assert store.read("a1").phase == "done"

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)

    assert AgentEventType.canceled in await _event_types(fake)
    state = store.read("a1")
    assert state.phase == "done"
    assert state.stop_requested_at is None  # never entered the machine


async def test_pending_job_without_a_log_is_confirmed_not_stranded(
    workdir, fake_redis
):
    # TC-44: a job still queued in scrapyd has written no log yet. Cancel it and
    # _resolve_status answers ``unknown`` (listjobs succeeded, the job is in no
    # list, no log on disk) -- identical to "scrapyd unreachable". Confirming a
    # stop with that would wait out the entire deadline on a job that is
    # demonstrably gone, and then keep kill_pending set forever.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, runner, consumer = _build(
        workdir, scrapyd, fake, clock, stop_confirm_timeout_seconds=600
    )
    job = await _start(fake, consumer, scrapyd)

    # move it to the pending queue and make sure it never wrote a log
    scrapyd.running.clear()
    scrapyd.pending.append({"id": job, "project": "demo", "spider": "phase1"})
    log_path = Path(store.read("a1").log_path)
    if log_path.exists():
        log_path.unlink()
    assert await runner.is_job_alive("a1") is True  # queued still counts

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)

    # scrapyd drops it from the queue. A job cancelled while queued never ran,
    # so it leaves no finished entry and no log behind.
    scrapyd.pending.clear()
    scrapyd.finished.clear()
    assert (await runner.status("a1", "e1")).status.value == "unknown"  # the trap
    assert await runner.is_job_alive("a1") is False  # what we actually ask

    await consumer.reconcile_started_attempts()

    assert store.read("a1") is None  # confirmed and cleaned in one tick
    assert not log_path.exists()
    assert (await _event_types(fake)).count(AgentEventType.canceled) == 1


async def test_a_batch_of_stops_does_not_starve_other_executions(
    workdir, fake_redis
):
    # TC-20: the reason the machine exists. The command consumer is serial, so
    # blocking inside a stop would freeze liveness for everything else --
    # default batch 16 x (10s + confirmation) is minutes of silence, far past
    # the server's event-stall threshold.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=120,
    )
    await consumer.setup()
    for ex in ("a1", "a2", "a3"):
        await fake.xadd(STREAM, to_stream_entry(_run_cmd(execution_id=ex)))
    await consumer.drain_once()
    assert len(scrapyd.running) == 3
    scrapyd.sticky_running = True  # nothing will die during this test

    listjobs_calls = 0
    original = scrapyd.handler

    def counting(request):
        nonlocal listjobs_calls
        if request.url.path == "/listjobs.json":
            listjobs_calls += 1
        return original(request)

    scrapyd.handler = counting  # type: ignore[method-assign]

    for ex in ("a1", "a2"):
        await fake.xadd(
            STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel, execution_id=ex))
        )
    calls_before = listjobs_calls
    await consumer.drain_once(claim_pending=False)
    # Handling two stops costs no polling at all: they only persist intent and
    # fire one TERM each.
    assert listjobs_calls == calls_before
    assert store.read("a1").stop_requested_at is not None
    assert store.read("a2").stop_requested_at is not None

    # ...and the untouched execution still gets its liveness beat this tick.
    await consumer.reconcile_started_attempts()
    beats = [
        e
        for e in [
            from_stream_entry(AgentEvent, f)
            for _id, f in await fake.entries(EVENT_STREAM)
        ]
        if e.type == AgentEventType.heartbeat
    ]
    assert any(b.execution_id == "a3" for b in beats)


async def test_intent_persisted_before_term_survives_a_restart(
    workdir, fake_redis
):
    # TC-23: the command is XACKed regardless, so a restart must resume from the
    # state file alone -- including the escalation to KILL, not just a TERM.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=600,
    )
    job = await _start(fake, consumer, scrapyd)
    paths = _write_log(store)
    scrapyd.fail_cancel_times = 1  # the first TERM never goes out
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    assert store.read("a1").stop_requested_at is not None
    assert store.read("a1").stop_escalation is None

    # "restart": brand new consumer over the same state directory
    _s2, _r2, revived = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=600,
    )
    await revived.setup()

    await revived.reconcile_started_attempts()  # retries the TERM
    assert store.read("a1").stop_escalation == "term"
    assert _signals(scrapyd) == [None, None]

    clock.advance(15)
    await revived.reconcile_started_attempts()  # escalates after restart
    assert _signals(scrapyd)[-1] == "KILL"
    assert store.read("a1").stop_escalation == "kill"

    scrapyd.sticky_running = False
    scrapyd.move_to_finished(job)
    await revived.reconcile_started_attempts()
    assert store.read("a1").result == "canceled"
    assert AgentEventType.canceled in await _event_types(fake)
    assert paths[0].exists()  # no cleanup was ever requested


async def test_terminal_persisted_but_unsent_is_republished_after_restart(
    workdir, fake_redis
):
    # TC-43: mark_done lands, then the process dies before emit runs. emit's own
    # durable outbox has nothing yet and the stop command is long since XACKed,
    # so without the terminal_pending latch the server would never learn the
    # attempt was cancelled and would eventually mis-judge it lost.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_confirm_timeout_seconds=60
    )
    await _start(fake, consumer, scrapyd)
    paths = _write_log(store)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)

    async def boom(*_a, **_kw):
        raise RuntimeError("process died before emit")

    consumer._events.emit_terminal = boom  # type: ignore[method-assign]
    clock.advance(120)
    try:
        await consumer.reconcile_started_attempts()
    except RuntimeError:
        pass

    state = store.read("a1")
    # one atomic write: done + result + kill_pending + terminal_pending
    assert state.phase == "done"
    assert state.result == "canceled"
    assert state.kill_pending is True
    assert state.terminal_pending is True
    assert AgentEventType.canceled not in await _event_types(fake)

    # restart: the terminal is republished without any command redelivery
    _s2, _r2, revived = _build(
        workdir, scrapyd, fake, clock, kill_retry_interval_seconds=30
    )
    await revived.setup()
    await revived.reconcile_started_attempts()

    assert (await _event_types(fake)).count(AgentEventType.canceled) == 1
    assert store.read("a1").terminal_pending is False
    assert store.read("a1").kill_pending is True  # reclamation still open

    # a cleanup request now arrives and must wait for the process
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await revived.drain_once(claim_pending=False)
    _assert_not_cleaned(store, paths)

    # reclamation continues: KILLs keep going out on the retry interval
    clock.advance(31)
    await revived.reconcile_started_attempts()
    assert _signals(scrapyd)[-1] == "KILL"
    _assert_not_cleaned(store, paths)

    # and only once the process is confirmed gone does the cleanup run
    scrapyd.sticky_running = False
    scrapyd.running.clear()
    await revived.reconcile_started_attempts()
    _assert_cleaned(store, paths)
    # the terminal was published exactly once across the whole sequence
    assert (await _event_types(fake)).count(AgentEventType.canceled) == 1


async def test_run_redelivery_during_a_stop_stays_silent(workdir, fake_redis):
    # TC-36: keeping phase=started for the machine opens a window where a
    # re-delivered run would republish the runner's status. After TERM that
    # status is ``canceled`` (the runner's own mark_canceled), which would
    # overwrite a reclaim's lost. A parked cleanup must also be unaffected.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_confirm_timeout_seconds=600
    )
    await _start(fake, consumer, scrapyd)
    paths = _write_log(store)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)
    # TERM landed and the job is gone, but the watchdog has not run yet
    assert store.read("a1").phase == "started"
    assert store.read("a1").stop_requested_at is not None
    assert store.read("a1").cleanup_pending is True
    before = await _event_types(fake)

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once(claim_pending=False)

    assert await _event_types(fake) == before  # nothing published
    _assert_not_cleaned(store, paths)  # and the redelivery cleaned nothing

    # The watchdog confirms the exit, keeps the attempt lost (no event), and
    # only then runs the parked cleanup -- which removes the state itself, so
    # the absence of a canceled event is what proves the reclaim semantics here.
    await consumer.reconcile_started_attempts()
    assert AgentEventType.canceled not in await _event_types(fake)
    _assert_cleaned(store, paths)  # the parked cleanup ran at the right time


async def test_cleanup_deferred_past_a_crash_is_recovered_on_restart(
    workdir, fake_redis
):
    # TC-31: mark_done and the deferred cleanup are two steps. Dying in between
    # leaves phase=done + cleanup_pending with the artifacts still on disk, and
    # the cleanup_logs command was XACKed long ago -- nothing will come back for
    # it unless the recovery entry point picks it up after a restart.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    job = await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)
    assert store.read("a1").cleanup_pending is True

    scrapyd.sticky_running = False
    scrapyd.move_to_finished(job)

    # simulate the process dying right after mark_done, before cleanup runs
    async def never_cleans(_execution_id):
        return None

    consumer._run_deferred_cleanup = never_cleans  # type: ignore[method-assign]
    await consumer.reconcile_started_attempts()

    state = store.read("a1")
    assert state.phase == "done"
    assert state.result == "canceled"
    assert state.kill_pending is False  # the exit WAS confirmed
    assert state.cleanup_pending is True  # ...but nothing was cleaned
    _assert_not_cleaned(store, paths)

    # restart: a fresh consumer over the same state directory finishes the job
    _s2, _r2, revived = _build(workdir, scrapyd, fake, clock)
    await revived.setup()
    await revived.reconcile_started_attempts()
    _assert_cleaned(store, paths)  # log AND workspace really deleted

    # idempotent: another pass over the now-empty directory is a no-op
    await revived.reconcile_started_attempts()
    _assert_cleaned(store, paths)


async def test_failed_cleanup_keeps_its_flag_and_is_retried(workdir, fake_redis):
    # TC-32: a cleanup that throws must not be silently forgotten. Cleanup is
    # best-effort deletion rather than a transaction, so some artifacts may
    # already be gone when it fails; what has to survive is the STATE and the
    # flag, because they are what make the retry reachable at all.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    job = await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)

    scrapyd.sticky_running = False
    scrapyd.move_to_finished(job)

    calls = {"n": 0}
    original_delete = store.delete

    def flaky(execution_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk hiccup")
        return original_delete(execution_id)

    store.delete = flaky  # type: ignore[method-assign]

    await consumer.reconcile_started_attempts()  # confirms exit, cleanup fails
    assert store.read("a1").phase == "done"
    assert store.read("a1").kill_pending is False
    assert store.read("a1").cleanup_pending is True  # flag kept for the retry

    await consumer.reconcile_started_attempts()  # recovery entry point retries
    _assert_cleaned(store, paths)
    assert calls["n"] == 2


async def test_reclaim_keeps_reclaiming_past_the_deadline_without_events(
    workdir, fake_redis
):
    # TC-39: the reclaim mirror of TC-37. The attempt stays lost (no event at
    # all), yet the process must still be hunted down and the parked cleanup
    # must wait for it.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock,
        stop_kill_after_seconds=10, stop_confirm_timeout_seconds=60,
        kill_retry_interval_seconds=30,
    )
    await _start(fake, consumer, scrapyd)
    paths = _write_log(store, workspace=True)
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)
    await fake.xadd(STREAM, to_stream_entry(_cleanup_cmd()))
    await consumer.drain_once(claim_pending=False)

    clock.advance(15)
    await consumer.reconcile_started_attempts()  # KILL
    clock.advance(60)
    await consumer.reconcile_started_attempts()  # deadline

    state = store.read("a1")
    assert state.result == "lost"
    assert state.kill_pending is True
    assert AgentEventType.canceled not in await _event_types(fake)
    _assert_not_cleaned(store, paths)

    # retries continue while it refuses to die
    await consumer.reconcile_started_attempts()
    assert _signals(scrapyd)[-1] == "KILL"
    clock.advance(31)
    await consumer.reconcile_started_attempts()
    assert _signals(scrapyd)[-1] == "KILL"
    _assert_not_cleaned(store, paths)

    scrapyd.sticky_running = False
    scrapyd.running.clear()
    await consumer.reconcile_started_attempts()
    _assert_cleaned(store, paths)
    assert AgentEventType.canceled not in await _event_types(fake)


async def test_duplicate_reclaim_mid_flight_does_not_report_a_terminal(
    workdir, fake_redis
):
    # Regression for round-01 R-01: the idempotence check used to live inside
    # _begin_stop, i.e. AFTER the reclaim branch read status(). By then TERM had
    # landed and the runner's own mark_canceled made a departed job resolve as
    # ``canceled``, so a redelivered reclaim published it and overwrote the
    # server's lost verdict.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(
        workdir, scrapyd, fake, clock, stop_confirm_timeout_seconds=600
    )
    await _start(fake, consumer, scrapyd)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)
    # TERM landed, the job is gone from scrapyd, the watchdog has not run yet
    assert store.read("a1").phase == "started"
    assert store.read("a1").canceled is True
    signals_before = len(scrapyd.cancels)
    types_before = await _event_types(fake)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)

    assert await _event_types(fake) == types_before  # nothing published
    assert len(scrapyd.cancels) == signals_before  # and no extra signal

    await consumer.reconcile_started_attempts()
    assert store.read("a1").result == "lost"
    assert AgentEventType.canceled not in await _event_types(fake)


async def test_reclaim_on_a_finished_attempt_reemits_without_reviving_it(
    workdir, fake_redis
):
    # TC-41: the attempt already wrapped up locally. Reclaim re-publishes the
    # real terminal it holds (agent>server override) and otherwise keeps quiet;
    # it must not signal anything or push the phase back to started.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, _r, consumer = _build(workdir, scrapyd, fake, clock)
    job = await _start(fake, consumer, scrapyd)
    scrapyd.move_to_finished(job)
    await consumer.reconcile_started_attempts()  # natural finish -> done
    assert store.read("a1").phase == "done"
    assert store.read("a1").result == "finished"
    cancels_before = len(scrapyd.cancels)

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)

    types = await _event_types(fake)
    assert types.count(AgentEventType.finished) == 2  # original + re-emit
    assert AgentEventType.canceled not in types
    assert len(scrapyd.cancels) == cancels_before  # no signal sent
    state = store.read("a1")
    assert state.phase == "done"
    assert state.stop_requested_at is None


async def test_term_raising_through_the_runner_still_retries_and_finishes(
    workdir, fake_redis
):
    # TC-22: distinct from TC-21. A transport error is converted to ScrapydError
    # by the client and then to a ``cancel_failed`` RESPONSE by the runner, so it
    # never reaches the state machine's exception handler. Anything the runner
    # does not convert -- a bug, an unexpected library error -- does, and that is
    # the dangerous case: _process XACKs the command even when a handler raises,
    # so if the intent were not already on disk the stop would vanish silently.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = Clock()
    store, runner, consumer = _build(
        workdir, scrapyd, fake, clock, stop_kill_after_seconds=10
    )
    job = await _start(fake, consumer, scrapyd)

    original_stop = runner.stop
    calls = {"n": 0}

    async def exploding_stop(execution_id, task_id, *, signal=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("unconverted failure inside the runner")
        return await original_stop(execution_id, task_id, signal=signal)

    runner.stop = exploding_stop  # type: ignore[method-assign]

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)

    # the exception was contained, the intent survived, nothing was signalled
    state = store.read("a1")
    assert state.stop_requested_at is not None
    assert state.stop_escalation is None
    assert scrapyd.cancels == []
    assert len(scrapyd.running) == 1

    # the command really is ACKed: re-draining delivers nothing, so the only
    # thing that can move this forward is the persisted intent
    assert await consumer.drain_once(claim_pending=True) == 0

    await consumer.reconcile_started_attempts()  # retry succeeds this tick
    assert calls["n"] == 2
    assert store.read("a1").stop_escalation == "term"
    assert _signals(scrapyd) == [None]
    assert job not in [j["id"] for j in scrapyd.running]

    await consumer.reconcile_started_attempts()  # confirmation lands next tick
    assert store.read("a1").result == "canceled"
    assert (await _event_types(fake)).count(AgentEventType.canceled) == 1
