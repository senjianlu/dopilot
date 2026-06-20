"""Schedule tests (phase 1.8): CRUD, trigger-now, overrides, repeated runs, and
the schedule-keyed timer coalesce (fire_timer)."""

from __future__ import annotations

from dopilot_server.config.settings import RedisSettings
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services import states, templates
from dopilot_server.services.executions import TaskOrigin, create_task, list_tasks
from dopilot_server.services.outbox import create_run_outbox


async def _create_template(client, seeder, **overrides) -> dict:
    artifact = overrides.pop("_artifact", None) or await seeder.build_artifact()
    body = {
        "name": "sched-template",
        "build_artifact_id": artifact.id,
        "spider": "phase1",
        "node_strategy": "all",
    }
    body.update(overrides)
    r = await client.post("/api/v1/templates", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _template_row(session, seeder, **fields):
    """Create an ExecutionTemplate directly via the service (for fire_timer)."""
    artifact = await seeder.build_artifact()
    data = {
        "name": "s",
        "build_artifact_id": artifact.id,
        "spider": "phase1",
        "node_strategy": "all",
    }
    data.update(fields)
    template = await templates.create_template(session, data)
    await session.commit()
    return template


async def _create_schedule(client, template_id, **overrides) -> dict:
    body = {
        "name": "every-30s",
        "execution_template_id": template_id,
        "trigger_type": "interval",
        "interval_seconds": 30,
        **overrides,
    }
    r = await client.post("/api/v1/schedules", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_and_list_schedule(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    created = await _create_schedule(exec_client, template["id"])
    assert created["execution_template_id"] == template["id"]
    assert created["trigger_type"] == "interval"
    assert created["interval_seconds"] == 30

    rows = (await exec_client.get("/api/v1/schedules")).json()["schedules"]
    assert any(s["id"] == created["id"] for s in rows)


async def test_create_schedule_unknown_template_404(exec_client):
    r = await exec_client.post(
        "/api/v1/schedules",
        json={"name": "x", "execution_template_id": "nope", "interval_seconds": 30},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "template.not_found"


async def test_create_schedule_invalid_interval_400(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "x",
            "execution_template_id": template["id"],
            "interval_seconds": 0,
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "schedule.invalid_interval"


async def test_create_cron_schedule(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    created = await _create_schedule(
        exec_client,
        template["id"],
        trigger_type="cron",
        cron="*/5 * * * *",
        interval_seconds=None,
    )
    assert created["trigger_type"] == "cron"
    assert created["cron"] == "*/5 * * * *"


async def test_create_cron_schedule_invalid_400(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "x",
            "execution_template_id": template["id"],
            "trigger_type": "cron",
            "cron": "not-a-cron",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "schedule.invalid_cron"


async def test_create_cron_schedule_invalid_range_400(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "x",
            "execution_template_id": template["id"],
            "trigger_type": "cron",
            "cron": "* * * * 8",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "schedule.invalid_cron"


async def test_schedule_cannot_override_build_artifact_400(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "x",
            "execution_template_id": template["id"],
            "interval_seconds": 30,
            "overrides": {"build_artifact_id": "other"},
        },
    )
    # build_artifact_id is not an allowed override key on the RunOverrides schema.
    assert r.status_code == 422


async def test_trigger_now_creates_task_from_snapshot(exec_client, seeder):
    await seeder.healthy_node()
    template = await _create_template(exec_client, seeder)
    schedule = await _create_schedule(exec_client, template["id"])

    r = await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    detail = (await exec_client.get(f"/api/v1/tasks/{body['task_id']}")).json()
    assert detail["source"] == states.TASK_SOURCE_TRIGGER_NOW
    assert detail["schedule_id"] == schedule["id"]
    assert detail["execution_template_id"] == template["id"]
    assert len(detail["executions"]) == 1


async def test_trigger_now_applies_overrides(exec_client, seeder):
    node = await seeder.healthy_node(agent_id="a1")
    template = await _create_template(
        exec_client, seeder, node_strategy="all", spider="phase1"
    )
    # override spider + node selection + a setting.
    schedule = await _create_schedule(
        exec_client,
        template["id"],
        overrides={
            "spider": "phase2",
            "node_strategy": "selected",
            "node_ids": [str(node.id)],
            "settings": {"DOWNLOAD_DELAY": "2"},
        },
    )
    r = await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    assert r.status_code == 200, r.text
    detail = (await exec_client.get(f"/api/v1/tasks/{r.json()['task_id']}")).json()
    # overrides won precedence over the template defaults.
    assert detail["node_strategy"] == "selected"
    assert detail["params"]["spider"] == "phase2"
    assert detail["params"]["settings"]["DOWNLOAD_DELAY"] == "2"
    # the build artifact is unchanged (never overridable).
    assert detail["build_artifact"]["project"] == "demo"


async def test_repeated_trigger_now_not_coalesced(exec_client, seeder):
    await seeder.healthy_node()
    template = await _create_template(exec_client, seeder)
    schedule = await _create_schedule(exec_client, template["id"])

    first = (
        await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    ).json()
    second = (
        await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    ).json()
    # Two distinct tasks even though the first is still active.
    assert first["task_id"] != second["task_id"]
    assert second["status"] == "queued"


def _dispatcher(sessionmaker, redis) -> CommandDispatcher:
    return CommandDispatcher(sessionmaker, CommandProducer(redis, RedisSettings()))


async def test_fire_timer_dispatches_when_no_backlog(
    db_session, exec_settings, seeder, test_sessionmaker, exec_redis
):
    await seeder.healthy_node()
    template = await _template_row(db_session, seeder)
    schedule = await sched_svc.create_schedule(
        db_session,
        {"name": "s", "execution_template_id": template.id, "interval_seconds": 30},
    )
    await db_session.commit()

    dispatcher = _dispatcher(test_sessionmaker, exec_redis)
    res = await sched_svc.fire_timer(
        db_session, exec_settings, dispatcher, schedule
    )
    assert res is not None
    assert res.status == "queued"
    tasks = await list_tasks(db_session)
    assert any(t.schedule_id == schedule.id for t in tasks)


async def test_fire_timer_coalesced_when_undispatched_backlog(
    db_session, exec_settings, seeder, test_sessionmaker, exec_redis
):
    await seeder.healthy_node()
    template = await _template_row(db_session, seeder)
    schedule = await sched_svc.create_schedule(
        db_session,
        {"name": "s", "execution_template_id": template.id, "interval_seconds": 30},
    )
    await db_session.commit()

    # Seed an undispatched backlog task for this schedule (queued + pending
    # outbox), as if Redis had been down on the prior firing.
    from dopilot_protocol import ExecutionRunRequest

    backlog = create_task(
        db_session,
        ExecutionRunRequest(
            artifact_type="scrapy", target="t", node_strategy="all",
            params={"project": "demo", "spider": "phase1"},
        ),
        TaskOrigin(source=states.TASK_SOURCE_TIMER, schedule_id=schedule.id),
    )
    create_run_outbox(
        db_session,
        execution_id=backlog.id,
        attempt_id="att-1",
        agent_id="agent-1",
        payload={},
        manual=False,
    )
    await db_session.commit()

    dispatcher = _dispatcher(test_sessionmaker, exec_redis)
    res = await sched_svc.fire_timer(
        db_session, exec_settings, dispatcher, schedule
    )
    # Suppressed: no new task created beyond the backlog one.
    assert res is None
    tasks = await list_tasks(db_session)
    assert len([t for t in tasks if t.schedule_id == schedule.id]) == 1


async def test_delete_schedule(exec_client, seeder):
    template = await _create_template(exec_client, seeder)
    schedule = await _create_schedule(exec_client, template["id"])
    r = await exec_client.delete(f"/api/v1/schedules/{schedule['id']}")
    assert r.status_code == 200
    assert (
        await exec_client.get(f"/api/v1/schedules/{schedule['id']}")
    ).status_code == 404
