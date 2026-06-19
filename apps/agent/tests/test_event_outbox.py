"""Agent event-outbox durability + republish tests (phase 1.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from dopilot_agent.deps import scrapyd_logs_dir, state_dir
from dopilot_agent.redis.events import EventPublisher
from dopilot_agent.runners.scrapyd import ScrapyRunner
from dopilot_agent.scrapyd.client import ScrapydClient
from dopilot_agent.state.store import StateStore
from dopilot_protocol import (
    EVENT_STREAM,
    AgentEvent,
    AgentEventType,
    from_stream_entry,
)
from redis.exceptions import ConnectionError as RedisConnectionError

from .conftest import FakeScrapyd

AGENT_ID = "agent-x"


def _publisher(workdir: Path, fake_redis_client, scrapyd: FakeScrapyd, *, outbox=True):
    client = ScrapydClient(
        base_url="http://scrapyd.test", transport=scrapyd.transport()
    )
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client, store=store, logs_dir=scrapyd_logs_dir(workdir)
    )
    pub = EventPublisher(
        redis=fake_redis_client,
        agent_id=AGENT_ID,
        runner=runner,
        store=store,
        outbox_dir=str(workdir / "outbox") if outbox else None,
    )
    return store, runner, pub


async def _events(fake) -> list[AgentEvent]:
    return [from_stream_entry(AgentEvent, f) for _id, f in await fake.entries(EVENT_STREAM)]


async def test_emit_success_clears_outbox(workdir, fake_redis):
    fake = fake_redis()
    _store, _runner, pub = _publisher(workdir, fake, FakeScrapyd())

    await pub.emit_running("e1", "a1", remote_job_id="job-1")

    events = await _events(fake)
    assert [e.type for e in events] == [AgentEventType.running]
    # outbox empty (file removed after successful XADD)
    assert list((workdir / "outbox").glob("*.json")) == []


async def test_emit_failure_queues_then_replays(workdir, fake_redis):
    fake = fake_redis()
    _store, _runner, pub = _publisher(workdir, fake, FakeScrapyd())

    fake.fail_xadd = True
    await pub.emit_terminal("e1", "a1", AgentEventType.finished, exit_code=0)
    # not on the stream, but durably queued
    assert await fake.entries(EVENT_STREAM) == []
    queued = list((workdir / "outbox").glob("*.json"))
    assert len(queued) == 1

    # Redis recovers -> replay drains the outbox onto the stream
    fake.fail_xadd = False
    replayed = await pub.replay_outbox()
    assert replayed == 1
    events = await _events(fake)
    assert [e.type for e in events] == [AgentEventType.finished]
    assert list((workdir / "outbox").glob("*.json")) == []


async def test_emit_without_outbox_propagates_failure(workdir, fake_redis):
    fake = fake_redis()
    _store, _runner, pub = _publisher(workdir, fake, FakeScrapyd(), outbox=False)
    fake.fail_xadd = True
    with pytest.raises(RedisConnectionError):
        await pub.emit_running("e1", "a1")


async def test_republish_started_resolves_live_status(workdir, fake_redis):
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, _runner, pub = _publisher(workdir, fake, scrapyd)
    # a started attempt whose job is running on scrapyd
    store.create_reserved(execution_id="e1", attempt_id="a1", project="demo", spider="phase1")
    store.promote_started("a1", scrapyd_job_id="job-1", log_path="/l/a1.log")
    scrapyd.add_running("job-1", "demo", "phase1")

    await pub.republish_current("e1", "a1")
    assert (await _events(fake))[-1].type is AgentEventType.running

    # job finishes -> republish now reports the agent-authoritative terminal
    scrapyd.move_to_finished("job-1")
    await pub.republish_current("e1", "a1")
    assert (await _events(fake))[-1].type is AgentEventType.finished


async def test_republish_done_replays_recorded_terminal(workdir, fake_redis):
    fake = fake_redis()
    store, _runner, pub = _publisher(workdir, fake, FakeScrapyd())
    store.create_reserved(execution_id="e1", attempt_id="a1", project="demo", spider="phase1")
    store.mark_done("a1", result="failed", error_code="spawn_aborted", lost_reason="spawn_aborted")

    await pub.republish_current("e1", "a1")
    ev = (await _events(fake))[-1]
    assert ev.type is AgentEventType.failed
    assert ev.lost_reason is not None and ev.lost_reason.value == "spawn_aborted"


async def test_republish_missing_state_emits_lost(workdir, fake_redis):
    fake = fake_redis()
    _store, _runner, pub = _publisher(workdir, fake, FakeScrapyd())
    await pub.republish_current("e1", "missing")
    ev = (await _events(fake))[-1]
    assert ev.type is AgentEventType.lost
    assert ev.lost_reason is not None and ev.lost_reason.value == "state_missing"
