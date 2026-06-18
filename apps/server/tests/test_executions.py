"""Execution API tests (phase 1): run, detail, list, cancel, logs snapshot."""

from __future__ import annotations

from dopilot_protocol import AttemptStatus
from dopilot_server.clients.agent import AgentUnreachableError
from dopilot_server.logs import files

RUN_BODY = {
    "task_type": "scrapy",
    "target": "demo:phase1",
    "node_strategy": "all",
    "params": {"project": "demo", "spider": "phase1"},
}


async def test_run_success_creates_execution_attempt_logindex(
    exec_client, db_session, fake_agent, seeder
):
    await seeder.healthy_node()
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    eid = body["execution_id"]
    assert "run" in fake_agent.call_names()

    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    assert detail.status_code == 200
    view = detail.json()
    assert view["status"] == "running"
    assert view["task_type"] == "scrapy"
    assert len(view["attempts"]) == 1
    attempt = view["attempts"][0]
    assert attempt["status"] == "running"
    assert attempt["remote_job_id"].startswith("job-")
    assert attempt["agent_id"] == "agent-1"


async def test_run_missing_params_400(exec_client, seeder):
    await seeder.healthy_node()
    r = await exec_client.post(
        "/api/v1/executions/run",
        json={
            "task_type": "scrapy",
            "target": "x",
            "node_strategy": "all",
            "params": {},
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "execution.invalid_params"


async def test_run_unknown_task_type_400(exec_client, seeder):
    await seeder.healthy_node()
    r = await exec_client.post(
        "/api/v1/executions/run",
        json={"task_type": "bogus", "target": "x", "params": {}},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "execution.unknown_task_type"


async def test_run_no_healthy_nodes_409(exec_client):
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 409
    assert r.json()["code"] == "execution.no_healthy_nodes"


async def test_run_agent_failure_records_failed(exec_client, fake_agent, seeder):
    await seeder.healthy_node()
    fake_agent.raises["run"] = AgentUnreachableError("http://agent:6800", "boom")
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 200
    eid = r.json()["execution_id"]
    assert r.json()["status"] == "failed"

    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    attempt = detail.json()["attempts"][0]
    assert attempt["status"] == "failed"
    assert attempt["error_code"]


async def test_run_immediate_terminal_status_rolls_up_not_stuck(
    exec_client, seeder, fake_agent
):
    """If the agent /run reports an already-terminal status, the execution must
    roll up to a terminal state, not sit in 'running' forever."""
    await seeder.healthy_node()
    fake_agent.run_status = AttemptStatus.finished
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 200
    assert r.json()["status"] == "complete"
    eid = r.json()["execution_id"]
    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    attempt = detail.json()["attempts"][0]
    assert attempt["status"] == "finished"
    assert attempt["finished_at"]


async def test_run_unknown_status_never_writes_null(exec_client, seeder, fake_agent):
    """An 'unknown' agent /run status must map to a concrete (running) state,
    never NULL (which would violate NOT NULL on PostgreSQL)."""
    await seeder.healthy_node()
    fake_agent.run_status = AttemptStatus.unknown
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    eid = r.json()["execution_id"]
    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    assert detail.json()["attempts"][0]["status"] == "running"


async def test_run_all_strategy_two_nodes_two_attempts(
    exec_client, seeder, fake_agent
):
    await seeder.healthy_node("a1", "http://a1:6800")
    await seeder.healthy_node("a2", "http://a2:6800")
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    eid = r.json()["execution_id"]
    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    assert len(detail.json()["attempts"]) == 2
    assert fake_agent.call_names().count("run") == 2


async def test_run_random_strategy_one_attempt(exec_client, seeder):
    await seeder.healthy_node("a1", "http://a1:6800")
    await seeder.healthy_node("a2", "http://a2:6800")
    body = {**RUN_BODY, "node_strategy": "random"}
    r = await exec_client.post("/api/v1/executions/run", json=body)
    eid = r.json()["execution_id"]
    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    assert len(detail.json()["attempts"]) == 1


async def test_list_executions(exec_client, seeder):
    await seeder.healthy_node()
    await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    r = await exec_client.get("/api/v1/executions")
    assert r.status_code == 200
    rows = r.json()["executions"]
    assert len(rows) >= 1
    assert rows[0]["attempt_count"] == 1


async def test_get_execution_404(exec_client):
    r = await exec_client.get("/api/v1/executions/does-not-exist")
    assert r.status_code == 404
    assert r.json()["code"] == "execution.not_found"


async def test_cancel_execution(exec_client, seeder, db_session, fake_agent):
    execution, attempt, _log = await seeder.running_execution()
    fake_agent.tail_script[attempt.id] = []
    r = await exec_client.post(f"/api/v1/executions/{execution.id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"
    assert "stop" in fake_agent.call_names()


async def test_logs_snapshot(exec_client, seeder, db_session):
    execution, attempt, log_file = await seeder.running_execution()
    files.append(log_file.storage_path, b"line1\nline2\n")
    log_file.size_bytes = files.size(log_file.storage_path)
    await db_session.commit()

    r = await exec_client.get(f"/api/v1/executions/{execution.id}/logs")
    assert r.status_code == 200
    body = r.json()
    assert body["attempt_id"] == attempt.id
    assert "line1" in body["content"]
    assert body["start_offset"] == 0
    assert body["end_offset"] == 12


async def test_logs_snapshot_unknown_attempt_404(exec_client, seeder):
    execution, _attempt, _log = await seeder.running_execution()
    r = await exec_client.get(
        f"/api/v1/executions/{execution.id}/logs?attempt_id=nope"
    )
    assert r.status_code == 404
    assert r.json()["code"] == "execution.attempt_not_found"
