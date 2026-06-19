"""Task-template tests (phase 1.7 packet 2): CRUD, run-from-template, snapshot
immutability, and zero-node no_target via a template run."""

from __future__ import annotations

from dopilot_protocol import AgentCommand, command_stream, from_stream_entry

TEMPLATE_BODY = {
    "name": "demo-template",
    "project": "demo",
    "spider": "phase1",
    "version": "v1",
    "settings": {"LOG_LEVEL": "INFO"},
    "args": {"page": "1"},
    "node_strategy": "all",
}


async def _commands(redis, agent_id="agent-1") -> list[AgentCommand]:
    entries = await redis.entries(command_stream(agent_id))
    return [from_stream_entry(AgentCommand, f) for _id, f in entries]


async def _create_template(client, **overrides) -> dict:
    body = {**TEMPLATE_BODY, **overrides}
    r = await client.post("/api/v1/templates", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_and_list_template(exec_client):
    created = await _create_template(exec_client)
    assert created["name"] == "demo-template"
    assert created["project"] == "demo"
    assert created["settings"] == {"LOG_LEVEL": "INFO"}

    r = await exec_client.get("/api/v1/templates")
    assert r.status_code == 200
    rows = r.json()["templates"]
    assert any(t["id"] == created["id"] for t in rows)


async def test_create_template_invalid_missing_spider_400(exec_client):
    r = await exec_client.post(
        "/api/v1/templates", json={"name": "x", "project": "demo"}
    )
    assert r.status_code == 400
    assert r.json()["code"] == "template.invalid_params"


async def test_get_template_404(exec_client):
    r = await exec_client.get("/api/v1/templates/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "template.not_found"


async def test_run_template_creates_task_from_snapshot(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    template = await _create_template(exec_client)

    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"

    detail = (await exec_client.get(f"/api/v1/executions/{body['execution_id']}")).json()
    assert detail["source"] == "manual"
    assert detail["template_id"] == template["id"]
    assert len(detail["attempts"]) == 1

    cmds = await _commands(exec_redis)
    assert len(cmds) == 1
    assert cmds[0].payload["spider"] == "phase1"
    assert cmds[0].payload["project"] == "demo"


async def test_template_edit_does_not_mutate_existing_task_snapshot(
    exec_client, seeder
):
    await seeder.healthy_node()
    template = await _create_template(exec_client)
    run = (
        await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    ).json()
    task_id = run["execution_id"]

    # Edit the template after the task exists.
    upd = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={"spider": "phase2", "project": "changed"},
    )
    assert upd.status_code == 200
    assert upd.json()["spider"] == "phase2"

    # The historical task snapshot is unchanged (immutability).
    detail = (await exec_client.get(f"/api/v1/executions/{task_id}")).json()
    assert detail["params"]["spider"] == "phase1"
    assert detail["params"]["project"] == "demo"


async def test_run_template_no_healthy_nodes_no_target(exec_client):
    template = await _create_template(exec_client)
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_target"
    detail = (await exec_client.get(f"/api/v1/executions/{body['execution_id']}")).json()
    assert detail["status_reason"] == "no_target"
    assert detail["attempts"] == []
    assert detail["template_id"] == template["id"]


async def test_delete_template(exec_client):
    template = await _create_template(exec_client)
    r = await exec_client.delete(f"/api/v1/templates/{template['id']}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert (
        await exec_client.get(f"/api/v1/templates/{template['id']}")
    ).status_code == 404


async def test_delete_template_referenced_by_schedule_409(exec_client):
    template = await _create_template(exec_client)
    schedule = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "every-30s",
            "template_id": template["id"],
            "trigger_type": "interval",
            "interval_seconds": 30,
        },
    )
    assert schedule.status_code == 200, schedule.text

    r = await exec_client.delete(f"/api/v1/templates/{template['id']}")

    assert r.status_code == 409
    assert r.json()["code"] == "template.in_use"
