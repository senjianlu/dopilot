"""A terminal that never reached ``emit`` must still converge on the server.

The agent-side unit tests prove the event gets republished after a restart; this
one closes the loop by feeding what actually landed on the stream into the
server's own ``apply_event``. That matters because the failure mode being
guarded against is not "no event in Redis" but "the server never learns the
attempt was cancelled and eventually mis-judges it lost" — and only the server
can demonstrate convergence.

Cross-application on purpose: the invariant spans the agent's durability latch
and the server's state machine, so testing either half alone would leave the
seam untested.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
    StopIntent,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)
from dopilot_server.db.base import Base
from dopilot_server.models.execution import Execution, Task
from dopilot_server.services import states
from dopilot_server.services.events import apply_event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .conftest import FakeScrapyd

AGENT_ID = "agent-x"
STREAM = command_stream(AGENT_ID)
EXECUTION_ID = "a1"
TASK_ID = "e1"


def _build(workdir: Path, scrapyd: FakeScrapyd, redis, now, **kw):
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
        redis=redis, agent_id=AGENT_ID, runner=runner, store=store,
        events=publisher, pending_idle_ms=0, now=now, **kw,
    )
    return store, consumer


def _run_cmd() -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.run,
        agent_id=AGENT_ID,
        task_id=TASK_ID,
        execution_id=EXECUTION_ID,
        payload={
            "command": "scrapy crawl phase1",
            "artifact": {"project": "demo"},
        },
        created_at="t",
    )


def _stop_cmd(intent: StopIntent) -> AgentCommand:
    return AgentCommand(
        command_id=uuid.uuid4().hex,
        type=AgentCommandType.stop,
        agent_id=AGENT_ID,
        task_id=TASK_ID,
        execution_id=EXECUTION_ID,
        intent=intent,
        created_at="t",
    )


async def _server_session():
    """A throwaway in-memory server database with the real schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    session = maker()
    session.add(
        Task(
            id=TASK_ID, artifact_type="scrapy", target="demo:phase1",
            status=states.TASK_RUNNING, params={},
        )
    )
    session.add(
        Execution(
            id=EXECUTION_ID, task_id=TASK_ID, agent_id=AGENT_ID,
            status=states.EXEC_RUNNING, error_detail={},
            started_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return engine, session


async def test_republished_terminal_converges_the_server_to_canceled(
    workdir, fake_redis
):
    # TC-43 (end to end): mark_done lands, the process dies before emit, and the
    # stop command is already XACKed. After a restart the agent republishes from
    # its state file; the server must then settle on canceled instead of waiting
    # the attempt out and calling it lost.
    fake = fake_redis()
    scrapyd = FakeScrapyd()
    clock = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    now = {"t": clock}
    store, consumer = _build(
        workdir, scrapyd, fake, lambda: now["t"],
        stop_confirm_timeout_seconds=60,
    )
    await consumer.setup()
    await fake.xadd(STREAM, to_stream_entry(_run_cmd()))
    await consumer.drain_once()
    scrapyd.sticky_running = True

    await fake.xadd(STREAM, to_stream_entry(_stop_cmd(StopIntent.cancel)))
    await consumer.drain_once(claim_pending=False)

    async def boom(*_a, **_kw):
        raise RuntimeError("process died before emit")

    consumer._events.emit_terminal = boom  # type: ignore[method-assign]
    now["t"] = now["t"].replace(minute=5)
    try:
        await consumer.reconcile_started_attempts()
    except RuntimeError:
        pass
    assert store.read(EXECUTION_ID).terminal_pending is True

    # Nothing is on the stream yet, so a server fed only what exists so far
    # would keep the attempt running (and eventually judge it lost).
    engine, session = await _server_session()
    try:
        for _id, fields in await fake.entries(EVENT_STREAM):
            await apply_event(
                session, from_stream_entry(AgentEvent, fields), uuid.uuid4().hex
            )
        await session.commit()
        execution = await session.get(Execution, EXECUTION_ID)
        assert execution.status != states.EXEC_CANCELED

        seen_before = len(await fake.entries(EVENT_STREAM))

        # restart -> the latch makes the agent republish it, with no command
        # redelivery of any kind
        _s2, revived = _build(
            workdir, scrapyd, fake, lambda: now["t"],
            stop_confirm_timeout_seconds=60,
        )
        await revived.setup()
        await revived.reconcile_started_attempts()

        new_entries = (await fake.entries(EVENT_STREAM))[seen_before:]
        events = [from_stream_entry(AgentEvent, f) for _id, f in new_entries]
        assert [e.type for e in events] == [AgentEventType.canceled]

        for event in events:
            await apply_event(session, event, uuid.uuid4().hex)
        await session.commit()

        execution = await session.get(Execution, EXECUTION_ID)
        task = await session.get(Task, TASK_ID)
        assert execution.status == states.EXEC_CANCELED
        assert task.status == states.TASK_CANCELED
        assert store.read(EXECUTION_ID).terminal_pending is False
    finally:
        await session.close()
        await engine.dispose()
