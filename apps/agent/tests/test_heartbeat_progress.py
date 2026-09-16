"""The heartbeat carries progress evidence, independently of the flood cap.

The server cannot tell "alive" from "working" on its own: scrapyd keeps listing
a spider stuck in its close phase. The job log's size is the evidence, so it
rides along on every heartbeat — and it must keep doing so even when the
log-size guard is switched off, which is a perfectly ordinary configuration.
"""

from __future__ import annotations

import uuid
from pathlib import Path

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
    command_stream,
    from_stream_entry,
    to_stream_entry,
)

from .conftest import FakeScrapyd

AGENT_ID = "agent-x"
STREAM = command_stream(AGENT_ID)


def _build(workdir: Path, scrapyd: FakeScrapyd, redis, **kw):
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
        **kw,
    )
    return store, consumer


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


async def _heartbeats(fake) -> list[AgentEvent]:
    entries = await fake.entries(EVENT_STREAM)
    events = [from_stream_entry(AgentEvent, f) for _id, f in entries]
    return [e for e in events if e.type == AgentEventType.heartbeat]


async def _start(fake, consumer, scrapyd):
    await consumer.setup()
    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    assert len(scrapyd.running) == 1


async def test_heartbeat_reports_the_log_size(workdir, fake_redis):
    # TC-14: guard on, log readable.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, consumer = _build(
        workdir, scrapyd, fake, max_job_log_bytes=1024 * 1024
    )
    await _start(fake, consumer, scrapyd)

    log_path = Path(store.read("a1").log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"x" * 321)

    await consumer.reconcile_started_attempts()

    beats = await _heartbeats(fake)
    assert beats and beats[-1].log_bytes == 321


async def test_sampling_survives_a_disabled_log_cap(workdir, fake_redis):
    # TC-15: the flood watchdog returns before reading anything when the cap is
    # 0. Sampling inside it would make every heartbeat report None here, and
    # no-progress detection would quietly never fire for these deployments.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, consumer = _build(workdir, scrapyd, fake, max_job_log_bytes=0)
    await _start(fake, consumer, scrapyd)

    log_path = Path(store.read("a1").log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"y" * 777)

    await consumer.reconcile_started_attempts()

    beats = await _heartbeats(fake)
    assert beats and beats[-1].log_bytes == 777
    assert store.read("a1").log_flood is False  # guard really is off


async def test_unreadable_log_reports_no_reading_at_all(workdir, fake_redis):
    # TC-16: "could not sample" must travel as None. Reporting 0 would look
    # like a real reading that never grows, i.e. a permanent false stall.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    store, consumer = _build(
        workdir, scrapyd, fake, max_job_log_bytes=1024 * 1024
    )
    await _start(fake, consumer, scrapyd)

    log_path = Path(store.read("a1").log_path)
    if log_path.exists():
        log_path.unlink()

    await consumer.reconcile_started_attempts()

    beats = await _heartbeats(fake)
    assert beats and beats[-1].log_bytes is None
