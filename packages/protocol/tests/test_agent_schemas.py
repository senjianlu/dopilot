"""Round-trip and defaults validation for the phase-1 server<->agent schemas."""

from __future__ import annotations

from dopilot_protocol import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentStopResponse,
    AttemptStatus,
    EggDeployResponse,
)


def test_attempt_status_values() -> None:
    assert [s.value for s in AttemptStatus] == [
        "pending",
        "running",
        "finished",
        "failed",
        "canceled",
        "unknown",
    ]
    # str-enum: equals its string value for painless JSON comparison.
    assert AttemptStatus.running == "running"


def test_agent_run_request_defaults_and_roundtrip() -> None:
    req = AgentRunRequest(
        task_id="t1",
        execution_id="e1",
        project="demo",
        spider="phase1",
    )
    assert req.version is None
    assert req.settings == {} and req.args == {}
    assert req.task_type == "scrapy"
    # mutable defaults must not be shared across instances
    other = AgentRunRequest(
        task_id="t2", execution_id="e2", project="demo", spider="phase1"
    )
    req.settings["LOG_LEVEL"] = "DEBUG"
    assert other.settings == {}
    assert AgentRunRequest.model_validate(req.model_dump()) == req


def test_agent_run_response_status_default() -> None:
    resp = AgentRunResponse(
        task_id="t1", execution_id="e1", remote_job_id="job-123"
    )
    assert resp.status is AttemptStatus.running
    assert AgentRunResponse.model_validate(resp.model_dump()) == resp


def test_agent_stop_response_roundtrip() -> None:
    resp = AgentStopResponse(
        task_id="t1",
        execution_id="e1",
        status=AttemptStatus.canceled,
        stopped=True,
    )
    assert resp.detail == {}
    assert AgentStopResponse.model_validate(resp.model_dump()) == resp


def test_agent_status_response_roundtrip() -> None:
    resp = AgentStatusResponse(
        task_id="t1",
        execution_id="e1",
        remote_job_id="job-123",
        status=AttemptStatus.finished,
        exit_code=0,
    )
    assert AgentStatusResponse.model_validate(resp.model_dump()) == resp
    # remote_job_id/exit_code optional
    minimal = AgentStatusResponse(
        task_id="t1", execution_id="e1", status=AttemptStatus.unknown
    )
    assert minimal.remote_job_id is None
    assert minimal.exit_code is None


def test_egg_deploy_response_roundtrip() -> None:
    resp = EggDeployResponse(
        project="demo", version="1700000000", spiders=["phase1"]
    )
    assert EggDeployResponse.model_validate(resp.model_dump()) == resp
    empty = EggDeployResponse(project="demo", version="1")
    assert empty.spiders == []
