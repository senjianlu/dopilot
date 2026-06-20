"""Task run/cancel/log API tests (phase 1.8.1, command-first).

Runs are dispatched by running an execution template (``POST /templates/{id}/run``)
— build artifacts are NO LONGER directly runnable. The parent run is a TASK and
the atomic per-node unit is an EXECUTION. Dispatch still goes over the Redis
command stream, now carrying a command-first payload (command + artifact context).
"""

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


async def _commands(redis, agent_id="agent-1") -> list[AgentCommand]:
    entries = await redis.entries(command_stream(agent_id))
    return [from_stream_entry(AgentCommand, f) for _id, f in entries]


async def _template(exec_client, seeder, *, spider="phase1", **overrides):
    """Seed an artifact + an execution template; return (artifact, template)."""
    artifact = await seeder.build_artifact()
    body = {
        "name": "t",
        "build_artifact_id": artifact.id,
        "command": f"scrapy crawl {spider}",
        "node_strategy": "all",
    }
    body.update(overrides)
    r = await exec_client.post("/api/v1/templates", json=body)
    assert r.status_code == 200, r.text
    return artifact, r.json()


async def _run(exec_client, seeder, *, spider="phase1", **overrides):
    """Seed a template + run it; return (artifact, response)."""
    artifact, template = await _template(
        exec_client, seeder, spider=spider, **overrides
    )
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    return artifact, r


async def test_run_dispatches_command_execution_queued(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    _artifact, r = await _run(exec_client, seeder)
    assert r.status_code == 200, r.text
    body = r.json()
    # task stays queued; convergence to running is via the agent event
    assert body["status"] == "queued"
    tid = body["task_id"]

    # a run command landed on the agent's command stream (command-first payload)
    cmds = await _commands(exec_redis)
    assert len(cmds) == 1
    assert cmds[0].type.value == "run"
    assert cmds[0].payload["command"] == "scrapy crawl phase1"
    # wire seam: the command payload still carries task_type
    assert cmds[0].payload["task_type"] == "scrapy"
    assert cmds[0].task_type == "scrapy"

    detail = await exec_client.get(f"/api/v1/tasks/{tid}")
    view = detail.json()
    assert view["status"] == "queued"
    assert view["artifact_type"] == "scrapy"
    assert len(view["executions"]) == 1
    execution = view["executions"][0]
    assert execution["status"] == "pending"  # not running until the event arrives
    assert execution["agent_id"] == "agent-1"
    assert execution["task_id"] == tid
    # the resolved build-artifact snapshot is frozen on the task
    assert view["build_artifact"]["project"] == "demo"
    assert view["source"] == "template"


async def test_run_carries_artifact_context_in_payload(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    _artifact, r = await _run(exec_client, seeder)
    assert r.status_code == 200, r.text
    cmds = await _commands(exec_redis)
    # command-first: project/version travel in the artifact context, not at top.
    artifact = cmds[0].payload["artifact"]
    assert artifact["project"] == "demo"
    assert artifact["version"] == "sha256-aaaaaaaaaaaa"
    assert artifact["fetch_path"].endswith("/egg")


async def test_direct_artifact_run_endpoint_removed(exec_client, seeder):
    # Build artifacts can no longer be run directly (endpoint removed).
    artifact = await seeder.build_artifact()
    r = await exec_client.post(
        f"/api/v1/artifacts/{artifact.id}/run", json={"spider": "phase1"}
    )
    assert r.status_code in (404, 405)


async def test_run_no_healthy_nodes_creates_no_target_task(exec_client, seeder):
    # No healthy node -> a persisted ZERO-execution task with terminal no_target.
    _artifact, r = await _run(exec_client, seeder)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_target"
    detail = await exec_client.get(f"/api/v1/tasks/{body['task_id']}")
    view = detail.json()
    assert view["status"] == "no_target"
    assert view["status_reason"] == "no_target"
    assert view["status_detail"]["healthy_count"] == 0
    assert view["executions"] == []  # no fake execution
    assert view["source"] == "template"


async def test_run_excludes_node_without_resolved_capability(exec_client, seeder):
    # A healthy node that lacks the scrapy capability must NOT be a dispatch
    # target for a scrapy artifact -> the task converges to no_target.
    await seeder.healthy_node(agent_id="script-only", scrapy=False)
    _artifact, r = await _run(exec_client, seeder)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_target"
    detail = await exec_client.get(f"/api/v1/tasks/{body['task_id']}")
    assert detail.json()["status_detail"]["healthy_count"] == 0


async def test_run_redis_down_503_dispatch_unavailable(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    exec_redis.fail_xadd = True  # Redis unavailable for publishing
    _artifact, r = await _run(exec_client, seeder)
    assert r.status_code == 503
    assert r.json()["code"] == "execution.dispatch_unavailable"
    tid = r.json()["detail"]["task_id"]
    detail = await exec_client.get(f"/api/v1/tasks/{tid}")
    view = detail.json()
    assert view["status"] == "failed"
    assert view["executions"][0]["status"] == "failed"
    assert view["executions"][0]["error_code"] == "dispatch_unavailable"


async def test_run_dispatch_unknown_202(exec_client, exec_redis, seeder, db_session):
    await seeder.healthy_node()
    _artifact, template = await _template(exec_client, seeder)
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
        r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    finally:
        db_session.commit = orig
        await db_session.rollback()

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"  # NOT "not delivered"
    assert await exec_redis.xlen(command_stream("agent-1")) == 1
    detail = await exec_client.get(f"/api/v1/tasks/{body['task_id']}")
    assert detail.json()["status"] == "queued"


async def test_run_all_strategy_two_nodes_two_commands(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node("a1", "http://a1:6800")
    await seeder.healthy_node("a2", "http://a2:6800")
    _artifact, r = await _run(exec_client, seeder, node_strategy="all")
    tid = r.json()["task_id"]
    detail = await exec_client.get(f"/api/v1/tasks/{tid}")
    assert len(detail.json()["executions"]) == 2
    assert len(await _commands(exec_redis, "a1")) == 1
    assert len(await _commands(exec_redis, "a2")) == 1


async def test_run_random_strategy_one_execution(exec_client, seeder):
    await seeder.healthy_node("a1", "http://a1:6800")
    await seeder.healthy_node("a2", "http://a2:6800")
    _artifact, r = await _run(exec_client, seeder, node_strategy="random")
    tid = r.json()["task_id"]
    detail = await exec_client.get(f"/api/v1/tasks/{tid}")
    assert len(detail.json()["executions"]) == 1


async def test_list_tasks(exec_client, seeder):
    await seeder.healthy_node()
    await _run(exec_client, seeder)
    r = await exec_client.get("/api/v1/tasks")
    assert r.status_code == 200
    rows = r.json()["tasks"]
    assert len(rows) >= 1
    assert rows[0]["execution_count"] == 1


async def test_get_task_404(exec_client):
    r = await exec_client.get("/api/v1/tasks/does-not-exist")
    assert r.status_code == 404
    assert r.json()["code"] == "task.not_found"


async def test_cancel_sends_stop_and_converges_via_event(
    exec_client, exec_redis, seeder, db_session
):
    task, execution, _log = await seeder.running_task()
    r = await exec_client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert r.status_code == 200
    # a stop(intent=cancel) command was dispatched to the agent
    cmds = await _commands(exec_redis)
    stop = [c for c in cmds if c.type.value == "stop"]
    assert len(stop) == 1 and stop[0].intent.value == "cancel"

    # the agent replies attempt.canceled -> task converges to canceled.
    ev = AgentEvent(
        event_id="ev1", agent_id="agent-1", task_id=task.id,
        execution_id=execution.id, type=AgentEventType.canceled, created_at="t",
    )
    await apply_event(db_session, ev, "m1")
    await db_session.commit()
    detail = await exec_client.get(f"/api/v1/tasks/{task.id}")
    assert detail.json()["status"] == states.TASK_CANCELED


async def test_logs_snapshot(exec_client, seeder, db_session):
    task, execution, log_file = await seeder.running_task()
    files.append(log_file.storage_path, b"line1\nline2\n")
    log_file.size_bytes = files.size(log_file.storage_path)
    await db_session.commit()

    r = await exec_client.get(f"/api/v1/tasks/{task.id}/logs")
    assert r.status_code == 200
    body = r.json()
    # public: the atomic execution id is `execution_id`; parent is `task_id`
    assert body["execution_id"] == execution.id
    assert body["task_id"] == task.id
    assert "line1" in body["content"]
    assert body["start_offset"] == 0
    assert body["end_offset"] == 12


async def test_logs_snapshot_unknown_execution_404(exec_client, seeder):
    task, _execution, _log = await seeder.running_task()
    r = await exec_client.get(
        f"/api/v1/tasks/{task.id}/logs?execution_id=nope"
    )
    assert r.status_code == 404
    assert r.json()["code"] == "task.execution_not_found"
