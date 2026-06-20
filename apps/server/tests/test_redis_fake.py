"""Self-test for the FakeRedisStreams double + the protocol wire codec.

The rest of the phase-1.5 reliability matrix trusts this double to model XADD /
XREADGROUP / XACK / XAUTOCLAIM / consumer-group PEL semantics faithfully, so it
is pinned here.
"""

from __future__ import annotations

import pytest
from dopilot_protocol import (
    COMMAND_GROUP,
    AgentCommand,
    AgentCommandType,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.mark.asyncio
async def test_ensure_group_is_idempotent(fake_redis) -> None:
    r = fake_redis()
    stream = command_stream("agent-01")
    await r.ensure_group(stream, COMMAND_GROUP)
    # second create must not raise (BUSYGROUP swallowed)
    await r.ensure_group(stream, COMMAND_GROUP)


@pytest.mark.asyncio
async def test_xadd_read_ack_roundtrip(fake_redis) -> None:
    r = fake_redis()
    stream = command_stream("agent-01")
    await r.ensure_group(stream, COMMAND_GROUP)

    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        payload={"project": "demo", "spider": "s1"},
        created_at="t",
    )
    await r.xadd(stream, to_stream_entry(cmd))

    msgs = await r.xreadgroup(COMMAND_GROUP, "agent-01", {stream: ">"}, count=10)
    assert len(msgs) == 1
    _stream, entries = msgs[0]
    assert len(entries) == 1
    msg_id, fields = entries[0]
    decoded = from_stream_entry(AgentCommand, fields)
    assert decoded == cmd

    # before ack the message is pending
    assert await r.pending_count(stream, COMMAND_GROUP) == 1
    await r.xack(stream, COMMAND_GROUP, msg_id)
    assert await r.pending_count(stream, COMMAND_GROUP) == 0


@pytest.mark.asyncio
async def test_xautoclaim_recovers_unacked_pending(fake_redis) -> None:
    r = fake_redis()
    stream = command_stream("agent-01")
    await r.ensure_group(stream, COMMAND_GROUP)
    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        created_at="t",
    )
    await r.xadd(stream, to_stream_entry(cmd))

    # consumer-1 reads but "crashes" before XACK
    await r.xreadgroup(COMMAND_GROUP, "consumer-1", {stream: ">"}, count=10)
    assert await r.pending_count(stream, COMMAND_GROUP) == 1

    # consumer-2 claims idle pending entries (min idle 0)
    _next, claimed, _deleted = await r.xautoclaim(
        stream, COMMAND_GROUP, "consumer-2", 0, "0-0"
    )
    assert len(claimed) == 1
    _id, fields = claimed[0]
    assert from_stream_entry(AgentCommand, fields).execution_id == "a1"


@pytest.mark.asyncio
async def test_fail_xadd_injects_redis_unavailable(fake_redis) -> None:
    r = fake_redis()
    stream = command_stream("agent-01")
    r.fail_xadd = True
    with pytest.raises(RedisConnectionError):
        await r.xadd(stream, {b"data": b"{}"})
    # per-stream fault
    r.fail_xadd = False
    r.fail_streams = {stream}
    with pytest.raises(RedisConnectionError):
        await r.xadd(stream, {b"data": b"{}"})


@pytest.mark.asyncio
async def test_shared_server_is_visible_across_clients(fake_redis, fake_server) -> None:
    producer = fake_redis(server=fake_server)
    consumer = fake_redis(server=fake_server)
    stream = command_stream("agent-01")
    await consumer.ensure_group(stream, COMMAND_GROUP)

    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        created_at="t",
    )
    await producer.xadd(stream, to_stream_entry(cmd))

    msgs = await consumer.xreadgroup(COMMAND_GROUP, "agent-01", {stream: ">"}, count=10)
    assert msgs and len(msgs[0][1]) == 1
