"""Round-trip + defaults tests for the frozen dopilot protocol contract."""

from __future__ import annotations

from dopilot_protocol import (
    CapabilitySet,
    ErrorResponse,
    ExecutionRunRequest,
    ExecutionRunResponse,
    HealthResponse,
    LogStream,
    TailRequest,
    TailResponse,
    __version__,
)


def test_version() -> None:
    assert __version__ == "0.0.0"


def test_capability_set_defaults_and_roundtrip() -> None:
    cs = CapabilitySet()
    assert cs.scrapy is False
    assert cs.script is False
    assert cs.docker is False

    dumped = cs.model_dump()
    assert dumped == {"scrapy": False, "script": False, "docker": False}
    assert CapabilitySet.model_validate(dumped) == cs

    custom = CapabilitySet(scrapy=True, script=True, docker=True)
    assert CapabilitySet.model_validate(custom.model_dump()) == custom


def test_error_response_detail_defaults_to_empty_dict() -> None:
    err = ErrorResponse(code="not_found", message_key="error.not_found")
    assert err.detail == {}

    # default_factory must yield independent dicts (no shared mutable default).
    other = ErrorResponse(code="x", message_key="y")
    assert err.detail is not other.detail

    dumped = err.model_dump()
    assert dumped == {
        "code": "not_found",
        "message_key": "error.not_found",
        "detail": {},
    }
    assert ErrorResponse.model_validate(dumped) == err

    with_detail = ErrorResponse(
        code="bad", message_key="error.bad", detail={"field": "name"}
    )
    assert ErrorResponse.model_validate(with_detail.model_dump()) == with_detail


def test_health_response_optional_fields_default_none() -> None:
    h = HealthResponse(status="ok", service="server", version="0.0.0")
    assert h.database is None
    assert h.agent_id is None
    assert h.capabilities is None
    assert h.workdir is None
    assert HealthResponse.model_validate(h.model_dump()) == h

    agent_health = HealthResponse(
        status="ok",
        service="agent",
        version="0.0.0",
        agent_id="agent-1",
        capabilities=CapabilitySet(script=True),
        workdir="/agent-data",
    )
    restored = HealthResponse.model_validate(agent_health.model_dump())
    assert restored == agent_health
    assert restored.capabilities == CapabilitySet(script=True)


def test_log_stream_enum_values() -> None:
    assert LogStream.log.value == "log"
    assert LogStream.stdout.value == "stdout"
    assert LogStream.stderr.value == "stderr"
    assert LogStream.system.value == "system"
    assert LogStream("log") is LogStream.log


def test_tail_request_defaults_and_roundtrip() -> None:
    req = TailRequest(execution_id="e1", attempt_id="a1")
    assert req.stream is LogStream.log
    assert req.offset == 0
    assert req.max_bytes == 262144

    dumped = req.model_dump()
    assert dumped["stream"] == "log"
    assert dumped["offset"] == 0
    assert dumped["max_bytes"] == 262144
    assert TailRequest.model_validate(dumped) == req

    explicit = TailRequest(
        execution_id="e2",
        attempt_id="a2",
        stream=LogStream.stderr,
        offset=128,
        max_bytes=4096,
    )
    assert TailRequest.model_validate(explicit.model_dump()) == explicit


def test_tail_response_roundtrip() -> None:
    resp = TailResponse(
        start_offset=0,
        end_offset=10,
        content="hello\nbye\n",
        eof=False,
        finished=False,
    )
    assert TailResponse.model_validate(resp.model_dump()) == resp


def test_execution_run_request_defaults_and_roundtrip() -> None:
    req = ExecutionRunRequest(task_type="script", target="job-1")
    assert req.node_strategy == "all"
    assert req.node_ids == []
    assert req.params == {}

    # default_factory must yield independent containers.
    other = ExecutionRunRequest(task_type="script", target="job-2")
    assert req.node_ids is not other.node_ids
    assert req.params is not other.params

    assert ExecutionRunRequest.model_validate(req.model_dump()) == req

    explicit = ExecutionRunRequest(
        task_type="scrapy",
        target="spider-a",
        node_strategy="push",
        node_ids=["n1", "n2"],
        params={"setting": "x"},
    )
    assert ExecutionRunRequest.model_validate(explicit.model_dump()) == explicit


def test_execution_run_response_roundtrip() -> None:
    resp = ExecutionRunResponse(execution_id="e1", status="queued")
    assert ExecutionRunResponse.model_validate(resp.model_dump()) == resp
