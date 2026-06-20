"""Agent command-consumer tests (phase 1.5)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from dopilot_agent.artifacts.cache import ArtifactCacheError
from dopilot_agent.deps import scrapyd_logs_dir, state_dir
from dopilot_agent.redis.commands import CommandConsumer
from dopilot_agent.redis.events import EventPublisher
from dopilot_agent.runners.scrapyd import ScrapyRunner
from dopilot_agent.scrapyd.client import ScrapydClient
from dopilot_agent.state.store import StateStore
from dopilot_protocol import (
    COMMAND_GROUP,
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


class FakeArtifactCache:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []
        self.error: ArtifactCacheError | None = None

    async def ensure(self, artifact: dict, *, attempt_id: str) -> None:
        self.calls.append((artifact, attempt_id))
        if self.error is not None:
            raise self.error


def _build(
    workdir: Path,
    fake_scrapyd: FakeScrapyd,
    redis,
    *,
    pending_idle_ms=0,
    artifact_cache=None,
):
    client = ScrapydClient(
        base_url="http://scrapyd.test", transport=fake_scrapyd.transport()
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
        pending_idle_ms=pending_idle_ms,
        artifact_cache=artifact_cache,
    )
    return store, runner, consumer


def _run_cmd(
    attempt_id="a1", execution_id="e1", command="scrapy crawl phase1"
) -> AgentCommand:
    # Command-first payload: the agent parses ``command`` and resolves
    # project/version from the build-artifact context.
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.run,
        agent_id=AGENT_ID,
        execution_id=execution_id,
        attempt_id=attempt_id,
        payload={"command": command, "artifact": {"project": "demo"}},
        created_at="t",
    )


def _artifact_run_cmd(attempt_id="a1", execution_id="e1") -> AgentCommand:
    cmd = _run_cmd(attempt_id=attempt_id, execution_id=execution_id)
    cmd.payload = {
        "command": "scrapy crawl phase1",
        "artifact": {
            "hash": "a" * 64,
            "project": "demo",
            "version": "sha256-aaaaaaaaaaaa",
            "fetch_path": "/api/v1/artifacts/scrapy/" + "a" * 64 + "/egg",
        },
    }
    return cmd


def _stop_cmd(intent: StopIntent, attempt_id="a1", execution_id="e1") -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.stop,
        agent_id=AGENT_ID,
        execution_id=execution_id,
        attempt_id=attempt_id,
        intent=intent,
        created_at="t",
    )


async def _events(fake) -> list[AgentEvent]:
    entries = await fake.entries(EVENT_STREAM)
    return [from_stream_entry(AgentEvent, f) for _id, f in entries]


async def _event_types(fake) -> list[AgentEventType]:
    return [e.type for e in await _events(fake)]


async def test_run_command_starts_and_emits(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    n = await consumer.drain_once()
    assert n == 1

    # spider scheduled exactly once, state file started
    assert scrapyd._counter == 1
    assert len(scrapyd.running) == 1
    state = store.read("a1")
    assert state.phase == "started" and state.scrapyd_job_id
    # accepted + running emitted, command acked (no pending)
    assert await _event_types(fake) == [AgentEventType.accepted, AgentEventType.running]
    assert await fake.pending_count(STREAM, COMMAND_GROUP) == 0


async def test_run_with_artifact_ensures_cache_before_schedule(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    artifact_cache = FakeArtifactCache()
    _store, _runner, consumer = _build(
        workdir, scrapyd, fake, artifact_cache=artifact_cache
    )
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_artifact_run_cmd()))
    await consumer.drain_once()

    assert len(artifact_cache.calls) == 1
    assert artifact_cache.calls[0][1] == "a1"
    assert scrapyd.running[0]["project"] == "demo"
    assert await _event_types(fake) == [AgentEventType.accepted, AgentEventType.running]


async def test_run_with_artifact_cache_failure_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    artifact_cache = FakeArtifactCache()
    artifact_cache.error = ArtifactCacheError(
        "fetch failed", detail={"hash": "a" * 64}
    )
    store, _runner, consumer = _build(
        workdir, scrapyd, fake, artifact_cache=artifact_cache
    )
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_artifact_run_cmd()))
    await consumer.drain_once()

    assert scrapyd._counter == 0
    assert store.read("a1").result == "failed"
    events = await _events(fake)
    assert [e.type for e in events] == [AgentEventType.accepted, AgentEventType.failed]
    assert events[-1].error_code == "artifact_error"


async def test_run_parses_command_args_and_settings(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    cmd = _run_cmd(command="scrapy crawl phase1 -a page=2 -s LOG_LEVEL=DEBUG")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()

    # the parsed spider/settings/args reached the local scrapyd schedule call.
    sched = scrapyd.schedules[0]
    assert sched["project"] == "demo"
    assert sched["spider"] == "phase1"
    assert sched["args"].get("page") == "2"
    assert sched["settings"].get("LOG_LEVEL") == "DEBUG"


async def test_run_invalid_command_emits_failed(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    cmd = _run_cmd(command="scrapy crawl phase1; rm -rf /")
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await consumer.drain_once()

    # nothing scheduled; a structured failed terminal is emitted.
    assert scrapyd._counter == 0
    assert store.read("a1").result == "failed"
    events = await _events(fake)
    assert events[-1].type is AgentEventType.failed
    assert events[-1].error_code == "command_invalid"


async def test_duplicate_attempt_id_does_not_restart(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    cmd = _run_cmd()
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await fake.xadd(STREAM, to_stream_entry(cmd))  # re-delivered same attempt_id
    await consumer.drain_once()

    # scheduled only once; the dup re-emits current status (running)
    assert scrapyd._counter == 1
    types = await _event_types(fake)
    assert types.count(AgentEventType.running) == 2  # initial + republish
    assert AgentEventType.accepted in types


async def test_reconcile_started_attempts_emits_finished(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    job_id = store.read("a1").scrapyd_job_id
    scrapyd.move_to_finished(job_id)

    reconciled = await consumer.reconcile_started_attempts()

    assert reconciled == 1
    assert store.read("a1").phase == "done"
    assert store.read("a1").result == "finished"
    assert await _event_types(fake) == [
        AgentEventType.accepted,
        AgentEventType.running,
        AgentEventType.finished,
    ]


async def test_concurrent_same_attempt_one_start(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    _store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    cmd = _run_cmd()
    await fake.xadd(STREAM, to_stream_entry(cmd))
    await fake.xadd(STREAM, to_stream_entry(cmd))
    msgs = await fake.xreadgroup(COMMAND_GROUP, AGENT_ID, {STREAM: ">"}, count=10)
    entries = msgs[0][1]
    # process both concurrently: the per-attempt lock + O_EXCL guarantee one start
    await asyncio.gather(
        consumer._process(entries[0][0], entries[0][1]),
        consumer._process(entries[1][0], entries[1][1]),
    )
    assert scrapyd._counter == 1


async def test_pending_command_recovered_after_crash(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake, pending_idle_ms=0)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    # "crash": read into the PEL but never process/ack
    await fake.xreadgroup(COMMAND_GROUP, AGENT_ID, {STREAM: ">"}, count=10)
    assert await fake.pending_count(STREAM, COMMAND_GROUP) == 1

    # restart recovery claims + processes the pending command idempotently
    claimed = await consumer._claim_pending()
    assert claimed == 1
    assert scrapyd._counter == 1
    assert store.read("a1").phase == "started"
    assert await fake.pending_count(STREAM, COMMAND_GROUP) == 0


async def test_reserved_orphan_recovered_as_spawn_aborted(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    # pre-create a reserved file with no spawn (crash between reserve & schedule)
    store.create_reserved(
        execution_id="e1", attempt_id="a1", project="demo", spider="phase1"
    )
    recovered = await consumer.recover_reserved_orphans()
    assert recovered == 1
    events = await _events(fake)
    assert events[-1].type is AgentEventType.failed
    assert events[-1].lost_reason is not None and events[-1].lost_reason.value == "spawn_aborted"
    # local state now terminal so a re-delivered run won't restart
    assert store.read("a1").phase == "done"


async def test_stop_cancel_emits_canceled_even_if_gone(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    # cancel an attempt with NO local state (process/state already gone)
    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once()
    assert await _event_types(fake) == [AgentEventType.canceled]


async def test_stop_cancel_after_running_emits_canceled(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)

    assert AgentEventType.canceled in await _event_types(fake)
    assert store.read("a1").result == "canceled"


async def test_stop_reclaim_running_kills_stays_lost(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    assert len(scrapyd.running) == 1

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.reclaim)))
    await consumer.drain_once(claim_pending=False)

    # process killed, attempt stays lost (NO canceled event emitted by reclaim)
    assert len(scrapyd.running) == 0
    assert store.read("a1").result == "lost"
    assert AgentEventType.canceled not in await _event_types(fake)


async def test_cleanup_logs_removes_state_and_log(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, runner, consumer = _build(workdir, scrapyd, fake)
    await consumer.setup()

    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    state = store.read("a1")
    log = Path(state.log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("body", encoding="utf-8")

    cleanup = AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.cleanup_logs,
        agent_id=AGENT_ID,
        execution_id="e1",
        attempt_id="a1",
        created_at="t",
    )
    await fake.xadd(STREAM, to_stream_entry(cleanup))
    await consumer.drain_once(claim_pending=False)

    assert store.read("a1") is None
    assert not log.exists()
