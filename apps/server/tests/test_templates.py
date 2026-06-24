"""Execution-template tests (phase 1.8): CRUD, mandatory build-artifact binding,
run-from-template, snapshot immutability, and zero-node no_target via a run."""

from __future__ import annotations

from dopilot_protocol import AgentCommand, command_stream, from_stream_entry


async def _commands(redis, agent_id="agent-1") -> list[AgentCommand]:
    entries = await redis.entries(command_stream(agent_id))
    return [from_stream_entry(AgentCommand, f) for _id, f in entries]


async def _create_template(client, seeder, **overrides) -> dict:
    artifact = overrides.pop("_artifact", None) or await seeder.build_artifact()
    body = {
        "name": "demo-template",
        "build_artifact_id": artifact.id,
        "command": "scrapy crawl phase1 -a page=1 -s LOG_LEVEL=INFO",
        "node_strategy": "all",
    }
    body.update(overrides)
    r = await client.post("/api/v1/templates", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_and_list_template(exec_client, seeder):
    created = await _create_template(exec_client, seeder)
    assert created["name"] == "demo-template"
    # project/version are resolved from the bound build artifact (read-only)
    assert created["project"] == "demo"
    # command-first: the authoritative execution input is the command string;
    # the legacy spider/settings/args fields are gone.
    assert created["command"] == "scrapy crawl phase1 -a page=1 -s LOG_LEVEL=INFO"
    assert "spider" not in created
    assert "settings" not in created
    assert created["build_artifact_id"]

    r = await exec_client.get("/api/v1/templates")
    assert r.status_code == 200
    rows = r.json()["templates"]
    assert any(t["id"] == created["id"] for t in rows)


async def test_create_template_missing_build_artifact_400(exec_client):
    r = await exec_client.post(
        "/api/v1/templates",
        json={"name": "x", "command": "scrapy crawl phase1"},
    )
    assert r.status_code == 422  # build_artifact_id is a required body field


async def test_create_template_missing_command_422(exec_client, seeder):
    artifact = await seeder.build_artifact()
    r = await exec_client.post(
        "/api/v1/templates",
        json={"name": "x", "build_artifact_id": artifact.id},
    )
    assert r.status_code == 422  # command is a required body field


async def test_create_template_invalid_command_400(exec_client, seeder):
    artifact = await seeder.build_artifact()
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "x",
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1; rm -rf /",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "command.invalid"


async def test_create_template_unknown_spider_400(exec_client, seeder):
    # The artifact exposes only "phase1"; a command for a different spider is
    # rejected server-side even though the command grammar is valid.
    artifact = await seeder.build_artifact()
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "x",
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl typo_spider",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "command.unknown_spider"


async def test_update_template_unknown_spider_400(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={"command": "scrapy crawl typo_spider"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "command.unknown_spider"


async def test_create_template_unknown_build_artifact_404(exec_client):
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "x",
            "build_artifact_id": "nope",
            "command": "scrapy crawl phase1",
        },
    )
    assert r.status_code == 404
    assert r.json()["code"] == "artifact.not_found"


async def test_create_template_reserved_artifact_not_runnable_400(
    exec_client, seeder
):
    # docker_image is still reserved/not runnable in phase 2b (python_wheel now is).
    artifact = await seeder.build_artifact(
        artifact_type="docker_image", package_format="image", sha256="c" * 64
    )
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "x",
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.not_runnable"


async def test_create_template_with_archived_artifact_400(exec_client, seeder):
    artifact = await seeder.build_artifact()
    archived = await exec_client.post(f"/api/v1/artifacts/{artifact.id}/archive")
    assert archived.status_code == 200, archived.text
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "x",
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.archived"


async def test_rebind_template_to_archived_artifact_400(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    other = await seeder.build_artifact(sha256="b" * 64)
    await exec_client.post(f"/api/v1/artifacts/{other.id}/archive")
    r = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={"build_artifact_id": other.id, "command": "scrapy crawl phase1"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.archived"


async def test_edit_template_bound_to_archived_artifact_allowed(
    exec_client, seeder
):
    # A template already bound to an artifact that was archived AFTER binding
    # stays editable for other fields (no rebind) — archive must not block edits.
    artifact = await seeder.build_artifact(spiders=("phase1", "phase2"))
    template = await _create_template(exec_client, seeder, _artifact=artifact)
    await exec_client.post(f"/api/v1/artifacts/{artifact.id}/archive")

    # Edit a non-binding field (command); keep the same (now archived) binding.
    r = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={"command": "scrapy crawl phase2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["command"] == "scrapy crawl phase2"

    # Even an explicit re-send of the SAME archived binding is not a rebind.
    r2 = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1",
        },
    )
    assert r2.status_code == 200, r2.text


async def test_run_template_bound_to_archived_artifact_still_runs(
    exec_client, exec_redis, seeder
):
    # The core invariant: archiving never blocks runs of an already-bound
    # template. Run + schedule dispatch resolve runnable-ONLY, no archive check.
    await seeder.healthy_node()
    artifact = await seeder.build_artifact()
    template = await _create_template(exec_client, seeder, _artifact=artifact)
    await exec_client.post(f"/api/v1/artifacts/{artifact.id}/archive")

    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"
    cmds = await _commands(exec_redis)
    assert len(cmds) == 1


async def test_schedule_dispatch_archived_artifact_still_fires(
    exec_client, exec_redis, seeder
):
    # Schedule trigger-now goes through the same runnable-only resolution; an
    # archived binding must still dispatch.
    await seeder.healthy_node()
    artifact = await seeder.build_artifact()
    template = await _create_template(exec_client, seeder, _artifact=artifact)
    schedule = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "arch-sched",
            "execution_template_id": template["id"],
            "trigger_type": "interval",
            "interval_seconds": 30,
        },
    )
    assert schedule.status_code == 200, schedule.text
    await exec_client.post(f"/api/v1/artifacts/{artifact.id}/archive")

    fired = await exec_client.post(
        f"/api/v1/schedules/{schedule.json()['id']}/trigger-now"
    )
    assert fired.status_code == 200, fired.text
    cmds = await _commands(exec_redis)
    assert len(cmds) == 1


async def test_get_template_404(exec_client):
    r = await exec_client.get("/api/v1/templates/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "template.not_found"


async def test_run_template_creates_task_from_snapshot(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node()
    template = await _create_template(exec_client, seeder)

    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"

    detail = (await exec_client.get(f"/api/v1/tasks/{body['task_id']}")).json()
    assert detail["source"] == "template"
    assert detail["execution_template_id"] == template["id"]
    assert detail["build_artifact"]["project"] == "demo"
    assert len(detail["executions"]) == 1

    cmds = await _commands(exec_redis)
    assert len(cmds) == 1
    # command-first payload: command + artifact context (no spider/settings/args)
    assert cmds[0].payload["command"].startswith("scrapy crawl phase1")
    assert cmds[0].payload["artifact"]["project"] == "demo"
    assert "spider" not in cmds[0].payload


async def test_template_edit_does_not_mutate_existing_task_snapshot(
    exec_client, seeder
):
    await seeder.healthy_node()
    # Artifact exposes both spiders so the post-create edit to phase2 is valid.
    artifact = await seeder.build_artifact(spiders=("phase1", "phase2"))
    template = await _create_template(exec_client, seeder, _artifact=artifact)
    run = (
        await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    ).json()
    task_id = run["task_id"]

    # Edit the template after the task exists.
    upd = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={"command": "scrapy crawl phase2"},
    )
    assert upd.status_code == 200
    assert upd.json()["command"] == "scrapy crawl phase2"

    # The historical task snapshot is unchanged (immutability). spider is the
    # value DERIVED from the command at creation time.
    detail = (await exec_client.get(f"/api/v1/tasks/{task_id}")).json()
    assert detail["params"]["command"].startswith("scrapy crawl phase1")
    assert detail["params"]["spider"] == "phase1"
    assert detail["params"]["project"] == "demo"


async def test_run_template_no_healthy_nodes_no_target(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_target"
    detail = (await exec_client.get(f"/api/v1/tasks/{body['task_id']}")).json()
    assert detail["status_reason"] == "no_target"
    assert detail["executions"] == []
    assert detail["execution_template_id"] == template["id"]


async def test_create_template_duplicate_name_409(exec_client, seeder):
    await _create_template(exec_client, seeder)
    artifact = await seeder.build_artifact()
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "demo-template",  # same name as the first template
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1",
            "node_strategy": "all",
        },
    )
    assert r.status_code == 409
    assert r.json()["code"] == "template.name_conflict"


async def test_rename_template_to_existing_name_409(exec_client, seeder):
    artifact = await seeder.build_artifact()
    first = await _create_template(exec_client, seeder)
    second = await _create_template(
        exec_client, seeder, _artifact=artifact, name="other-template"
    )
    # Rename the second onto the first's name -> conflict.
    r = await exec_client.put(
        f"/api/v1/templates/{second['id']}",
        json={"name": first["name"]},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "template.name_conflict"


async def test_rename_template_to_same_name_ok(exec_client, seeder):
    # Self-exclusion: updating a template without changing its name is allowed.
    template = await _create_template(exec_client, seeder)
    r = await exec_client.put(
        f"/api/v1/templates/{template['id']}",
        json={"name": template["name"], "description": "edited"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "edited"


async def test_delete_template(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.delete(f"/api/v1/templates/{template['id']}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert (
        await exec_client.get(f"/api/v1/templates/{template['id']}")
    ).status_code == 404


async def test_delete_template_referenced_by_schedule_409(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    schedule = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "every-30s",
            "execution_template_id": template["id"],
            "trigger_type": "interval",
            "interval_seconds": 30,
        },
    )
    assert schedule.status_code == 200, schedule.text

    r = await exec_client.delete(f"/api/v1/templates/{template['id']}")

    assert r.status_code == 409
    assert r.json()["code"] == "template.in_use"
