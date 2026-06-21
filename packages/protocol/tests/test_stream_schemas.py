"""Round-trip, defaults, enum-value and wire-codec tests for the phase-1.5
Redis Streams protocol (``dopilot_protocol.streams``)."""

from __future__ import annotations

import base64

from dopilot_protocol import (
    COMMAND_GROUP,
    EVENT_GROUP,
    EVENT_STREAM,
    LOG_GROUP,
    LOG_STREAM,
    AgentCommand,
    AgentCommandType,
    AgentEvent,
    AgentEventType,
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentLogEvent,
    CapabilitySet,
    LogStream,
    LostReason,
    StopIntent,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)


def test_stream_topology_constants() -> None:
    assert command_stream("agent-01") == "dopilot:agent:agent-01:commands"
    assert EVENT_STREAM == "dopilot:server:agent-events"
    assert LOG_STREAM == "dopilot:server:logs"
    assert COMMAND_GROUP == "agent"
    assert EVENT_GROUP == "server-events"
    assert LOG_GROUP == "server-logs"


def test_command_type_and_stop_intent_values() -> None:
    assert [t.value for t in AgentCommandType] == ["run", "stop", "cleanup_logs"]
    assert [i.value for i in StopIntent] == ["cancel", "reclaim"]


def test_agent_command_defaults_and_roundtrip() -> None:
    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        created_at="2026-06-19T00:00:00Z",
    )
    assert cmd.intent is None
    assert cmd.payload == {} and cmd.task_type == "scrapy"
    # mutable default independence
    other = AgentCommand(
        command_id="c2",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="e2",
        execution_id="a2",
        created_at="2026-06-19T00:00:00Z",
    )
    cmd.payload["project"] = "demo"
    assert other.payload == {}
    assert AgentCommand.model_validate(cmd.model_dump()) == cmd


def test_run_command_python_wheel_task_type_roundtrip() -> None:
    from dopilot_protocol import PythonWheelRunPayload

    payload = PythonWheelRunPayload(
        shell_command="python -m main",
        artifact={"sha256": "a" * 64, "fetch_path": "/x/wheel"},
    ).model_dump()
    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="t1",
        execution_id="x1",
        task_type="python_wheel",
        payload=payload,
        created_at="2026-06-21T00:00:00Z",
    )
    assert cmd.task_type == "python_wheel"
    assert cmd.payload["shell_command"] == "python -m main"
    # full wire round trip (stream codec) preserves the discriminator + payload.
    assert from_stream_entry(AgentCommand, to_stream_entry(cmd)) == cmd


def test_stop_command_carries_intent() -> None:
    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.stop,
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        intent=StopIntent.cancel,
        created_at="t",
    )
    assert AgentCommand.model_validate(cmd.model_dump()).intent is StopIntent.cancel


def test_event_type_values_and_helpers() -> None:
    assert AgentEventType.running == "attempt.running"
    assert AgentEventType.finished == "attempt.finished"
    assert AgentEventType.lost.short == "lost"
    assert AgentEventType.running.short == "running"
    # terminals
    for t in (AgentEventType.finished, AgentEventType.failed, AgentEventType.canceled):
        assert t.is_terminal and t.is_authoritative_terminal
    # lost is terminal but NOT authoritative (soft terminal)
    assert AgentEventType.lost.is_terminal
    assert not AgentEventType.lost.is_authoritative_terminal
    # non-terminals
    assert not AgentEventType.running.is_terminal
    assert not AgentEventType.accepted.is_terminal


def test_lost_reason_source_split() -> None:
    assert LostReason.heartbeat_timeout.source == "server"
    assert LostReason.event_stall.source == "server"
    assert LostReason.state_missing.source == "agent"
    assert LostReason.process_missing.source == "agent"
    assert LostReason.runner_recovered_unknown.source == "agent"
    assert LostReason.spawn_aborted.source == "agent"


def test_agent_event_status_is_computed_from_type() -> None:
    ev = AgentEvent(
        event_id="ev1",
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        type=AgentEventType.running,
        remote_job_id="job-123",
        created_at="t",
    )
    dumped = ev.model_dump()
    assert dumped["status"] == "running"  # computed field on the wire
    assert ev.error_detail == {} and ev.lost_reason is None
    # round-trip: computed status is ignored on input, recomputed from type
    assert AgentEvent.model_validate(dumped) == ev


def test_agent_event_lost_reason_roundtrip() -> None:
    ev = AgentEvent(
        event_id="ev1",
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        type=AgentEventType.lost,
        lost_reason=LostReason.process_missing,
        created_at="t",
    )
    assert ev.model_dump()["status"] == "lost"
    restored = AgentEvent.model_validate(ev.model_dump())
    assert restored.lost_reason is LostReason.process_missing


def test_agent_log_event_base64_byte_fidelity() -> None:
    # invalid-UTF-8 bytes mid-stream must survive the base64 round-trip
    raw = b"line one\n\xff\xfe partial-utf8 \x00\x01\x02"
    ev = AgentLogEvent(
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        offset=4096,
        content_b64=base64.b64encode(raw).decode("ascii"),
        size_bytes=len(raw),
        eof=False,
        created_at="t",
    )
    assert ev.stream is LogStream.log
    restored = AgentLogEvent.model_validate(ev.model_dump())
    assert base64.b64decode(restored.content_b64) == raw
    assert restored.size_bytes == len(raw)


def test_heartbeat_request_reuses_capability_set() -> None:
    hb = AgentHeartbeatRequest(
        agent_id="agent-01",
        version="0.1.0",
        capabilities=CapabilitySet(scrapy=True),
        load={"running_attempts": 2},
        detail={"scrapyd": {"running": True, "port": 6801}},
        reported_at="t",
    )
    assert isinstance(hb.capabilities, CapabilitySet)
    restored = AgentHeartbeatRequest.model_validate(hb.model_dump())
    assert restored.capabilities == CapabilitySet(scrapy=True)
    # mutable default independence
    a = AgentHeartbeatRequest(agent_id="x", version="1", reported_at="t")
    b = AgentHeartbeatRequest(agent_id="y", version="1", reported_at="t")
    assert a.load is not b.load and a.detail is not b.detail
    assert a.capabilities == CapabilitySet()


def test_heartbeat_response_defaults() -> None:
    resp = AgentHeartbeatResponse(server_time="t")
    assert resp.ok is True
    assert AgentHeartbeatResponse.model_validate(resp.model_dump()) == resp


def test_wire_codec_roundtrip_for_each_message() -> None:
    cmd = AgentCommand(
        command_id="c1",
        type=AgentCommandType.run,
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        payload={"project": "demo", "spider": "s1"},
        created_at="t",
    )
    entry = to_stream_entry(cmd)
    assert set(entry.keys()) == {b"data"}
    assert from_stream_entry(AgentCommand, entry) == cmd

    ev = AgentEvent(
        event_id="ev1",
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        type=AgentEventType.finished,
        exit_code=0,
        created_at="t",
    )
    assert from_stream_entry(AgentEvent, to_stream_entry(ev)) == ev

    log = AgentLogEvent(
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        offset=0,
        content_b64=base64.b64encode(b"hi").decode("ascii"),
        size_bytes=2,
        created_at="t",
    )
    assert from_stream_entry(AgentLogEvent, to_stream_entry(log)) == log


def test_wire_codec_accepts_str_keyed_fields() -> None:
    # redis with decode_responses=True would hand back str keys/values
    ev = AgentEvent(
        event_id="ev1",
        agent_id="agent-01",
        task_id="e1",
        execution_id="a1",
        type=AgentEventType.running,
        created_at="t",
    )
    str_fields = {"data": ev.model_dump_json()}
    assert from_stream_entry(AgentEvent, str_fields) == ev
