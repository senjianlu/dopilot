"""Execution API tests (phase 1.5): run/cancel dispatch over the command stream."""

from __future__ import annotations

from dopilot_protocol import (
    AgentCommand,
    AgentEvent,
    AgentEventType,
    command_stream,
    from_stream_entry,
)
from dopilot_server.logs import files
from dopilot_server.services import states
from dopilot_server.services.events import apply_event

RUN_BODY = {
    "task_type": "scrapy",
    "target": "demo:phase1",
    "node_strategy": "all",
    "params": {"project": "demo", "spider": "phase1"},
}


async def _commands(redis, agent_id="agent-1") -> list[AgentCommand]:
    entries = await redis.entries(command_stream(agent_id))
    return [from_stream_entry(AgentCommand, f) for _id, f in entries]


async def test_run_dispatches_command_execution_queued(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    # execution stays queued; convergence to running is via the agent event
    assert body["status"] == "queued"
    eid = body["execution_id"]

    # a run command landed on the agent's command stream
    cmds = await _commands(exec_redis)
    assert len(cmds) == 1
    assert cmds[0].type.value == "run"
    assert cmds[0].payload["spider"] == "phase1"

    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    view = detail.json()
    assert view["status"] == "queued"
    assert len(view["attempts"]) == 1
    attempt = view["attempts"][0]
    assert attempt["status"] == "pending"  # not running until the event arrives
    assert attempt["agent_id"] == "agent-1"


async def test_run_with_artifact_uses_artifact_project_and_payload(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    artifact = {
        "hash": "a" * 64,
        "filename": "demo.egg",
        "project": "demo",
        "version": "sha256-aaaaaaaaaaaa",
        "size_bytes": 123,
        "fetch_path": "/api/v1/artifacts/scrapy/" + "a" * 64 + "/egg",
    }
    body = {
        "task_type": "scrapy",
        "target": "demo:phase1",
        "node_strategy": "all",
        "params": {"spider": "phase1", "artifact": artifact},
    }

    r = await exec_client.post("/api/v1/executions/run", json=body)

    assert r.status_code == 200, r.text
    cmds = await _commands(exec_redis)
    assert cmds[0].payload["project"] == "demo"
    assert cmds[0].payload["version"] == "sha256-aaaaaaaaaaaa"
    assert cmds[0].payload["artifact"] == artifact


async def test_run_missing_params_400(exec_client, seeder):
    await seeder.healthy_node()
    r = await exec_client.post(
        "/api/v1/executions/run",
        json={"task_type": "scrapy", "target": "x", "node_strategy": "all", "params": {}},
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


async def test_run_redis_down_503_dispatch_unavailable(
    exec_client, exec_redis, seeder, db_session
):
    await seeder.healthy_node()
    exec_redis.fail_xadd = True  # Redis unavailable for publishing
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    assert r.status_code == 503
    assert r.json()["code"] == "execution.dispatch_unavailable"
    # execution + attempt marked failed (no half-baked queued)
    eid = r.json()["detail"]["execution_id"]
    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    view = detail.json()
    assert view["status"] == "failed"
    assert view["attempts"][0]["status"] == "failed"
    assert view["attempts"][0]["error_code"] == "dispatch_unavailable"


async def test_run_dispatch_unknown_202(exec_client, exec_redis, seeder, db_session):
    await seeder.healthy_node()
    # XADD succeeds but the sent-mark commit (the 2nd commit in run) is lost.
    orig = db_session.commit
    state = {"n": 0}

    async def flaky():
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("sent-mark commit lost")
        return await orig()

    db_session.commit = flaky
    try:
        r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    finally:
        db_session.commit = orig
        await db_session.rollback()

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"  # NOT "not delivered"
    # the command really reached Redis (so the agent may already be running it)
    assert await exec_redis.xlen(command_stream("agent-1")) == 1
    # execution stays queued; the agent's attempt.running event converges it
    detail = await exec_client.get(f"/api/v1/executions/{body['execution_id']}")
    assert detail.json()["status"] == "queued"


async def test_run_all_strategy_two_nodes_two_commands(exec_client, exec_redis, seeder):
    await seeder.healthy_node("a1", "http://a1:6800")
    await seeder.healthy_node("a2", "http://a2:6800")
    r = await exec_client.post("/api/v1/executions/run", json=RUN_BODY)
    eid = r.json()["execution_id"]
    detail = await exec_client.get(f"/api/v1/executions/{eid}")
    assert len(detail.json()["attempts"]) == 2
    # one run command per agent stream
    assert len(await _commands(exec_redis, "a1")) == 1
    assert len(await _commands(exec_redis, "a2")) == 1


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


async def test_cancel_sends_stop_and_converges_via_event(
    exec_client, exec_redis, seeder, db_session
):
    execution, attempt, _log = await seeder.running_execution()
    r = await exec_client.post(f"/api/v1/executions/{execution.id}/cancel")
    assert r.status_code == 200
    # a stop(intent=cancel) command was dispatched to the agent
    cmds = await _commands(exec_redis)
    stop = [c for c in cmds if c.type.value == "stop"]
    assert len(stop) == 1 and stop[0].intent.value == "cancel"

    # the agent replies attempt.canceled -> execution converges to canceled
    ev = AgentEvent(
        event_id="ev1", agent_id="agent-1", execution_id=execution.id,
        attempt_id=attempt.id, type=AgentEventType.canceled, created_at="t",
    )
    await apply_event(db_session, ev, "m1")
    await db_session.commit()
    detail = await exec_client.get(f"/api/v1/executions/{execution.id}")
    assert detail.json()["status"] == states.EXEC_CANCELED


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
