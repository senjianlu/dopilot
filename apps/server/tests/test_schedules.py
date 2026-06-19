"""Schedule tests (phase 1.7 packet 2): CRUD, trigger-now, repeated runs, and
the schedule-keyed timer coalesce (fire_timer)."""

from __future__ import annotations

from dopilot_server.config.settings import RedisSettings
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services import states, templates
from dopilot_server.services.executions import TaskOrigin, create_task, list_tasks
from dopilot_server.services.outbox import create_run_outbox

TEMPLATE_BODY = {
    "name": "sched-template",
    "project": "demo",
    "spider": "phase1",
    "node_strategy": "all",
}


async def _create_template(client) -> dict:
    r = await client.post("/api/v1/templates", json=TEMPLATE_BODY)
    assert r.status_code == 200, r.text
    return r.json()


async def _create_schedule(client, template_id, **overrides) -> dict:
    body = {
        "name": "every-30s",
        "template_id": template_id,
        "trigger_type": "interval",
        "interval_seconds": 30,
        **overrides,
    }
    r = await client.post("/api/v1/schedules", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_and_list_schedule(exec_client):
    template = await _create_template(exec_client)
    created = await _create_schedule(exec_client, template["id"])
    assert created["template_id"] == template["id"]
    assert created["trigger_type"] == "interval"
    assert created["interval_seconds"] == 30

    rows = (await exec_client.get("/api/v1/schedules")).json()["schedules"]
    assert any(s["id"] == created["id"] for s in rows)


async def test_create_schedule_unknown_template_404(exec_client):
    r = await exec_client.post(
        "/api/v1/schedules",
        json={"name": "x", "template_id": "nope", "interval_seconds": 30},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "template.not_found"


async def test_create_schedule_invalid_interval_400(exec_client):
    template = await _create_template(exec_client)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={"name": "x", "template_id": template["id"], "interval_seconds": 0},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "schedule.invalid_interval"


async def test_create_cron_schedule(exec_client):
    template = await _create_template(exec_client)
    created = await _create_schedule(
        exec_client,
        template["id"],
        trigger_type="cron",
        cron="*/5 * * * *",
        interval_seconds=None,
    )
    assert created["trigger_type"] == "cron"
    assert created["cron"] == "*/5 * * * *"


async def test_create_cron_schedule_invalid_400(exec_client):
    template = await _create_template(exec_client)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "x",
            "template_id": template["id"],
            "trigger_type": "cron",
            "cron": "not-a-cron",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "schedule.invalid_cron"


async def test_create_cron_schedule_invalid_range_400(exec_client):
    template = await _create_template(exec_client)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "x",
            "template_id": template["id"],
            "trigger_type": "cron",
            "cron": "* * * * 8",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "schedule.invalid_cron"


async def test_trigger_now_creates_task_from_snapshot(
    exec_client, seeder
):
    await seeder.healthy_node()
    template = await _create_template(exec_client)
    schedule = await _create_schedule(exec_client, template["id"])

    r = await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    detail = (await exec_client.get(f"/api/v1/executions/{body['execution_id']}")).json()
    assert detail["source"] == states.TASK_SOURCE_TRIGGER_NOW
    assert detail["schedule_id"] == schedule["id"]
    assert detail["template_id"] == template["id"]
    assert len(detail["attempts"]) == 1


async def test_repeated_trigger_now_not_coalesced(exec_client, seeder):
    await seeder.healthy_node()
    template = await _create_template(exec_client)
    schedule = await _create_schedule(exec_client, template["id"])

    first = (
        await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    ).json()
    second = (
        await exec_client.post(f"/api/v1/schedules/{schedule['id']}/trigger-now")
    ).json()
    # Two distinct tasks even though the first is still active.
    assert first["execution_id"] != second["execution_id"]
    assert second["status"] == "queued"


def _dispatcher(sessionmaker, redis) -> CommandDispatcher:
    return CommandDispatcher(sessionmaker, CommandProducer(redis, RedisSettings()))


async def test_fire_timer_dispatches_when_no_backlog(
    db_session, exec_settings, seeder, test_sessionmaker, exec_redis
):
    await seeder.healthy_node()
    template = templates.create_template(db_session, dict(TEMPLATE_BODY))
    schedule = await sched_svc.create_schedule(
        db_session,
        {"name": "s", "template_id": template.id, "interval_seconds": 30},
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
    template = templates.create_template(db_session, dict(TEMPLATE_BODY))
    schedule = await sched_svc.create_schedule(
        db_session,
        {"name": "s", "template_id": template.id, "interval_seconds": 30},
    )
    await db_session.commit()

    # Seed an undispatched backlog task for this schedule (queued + pending
    # outbox), as if Redis had been down on the prior firing.
    from dopilot_protocol import ExecutionRunRequest

    backlog = create_task(
        db_session,
        ExecutionRunRequest(
            task_type="scrapy", target="t", node_strategy="all",
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


async def test_delete_schedule(exec_client):
    template = await _create_template(exec_client)
    schedule = await _create_schedule(exec_client, template["id"])
    r = await exec_client.delete(f"/api/v1/schedules/{schedule['id']}")
    assert r.status_code == 200
    assert (
        await exec_client.get(f"/api/v1/schedules/{schedule['id']}")
    ).status_code == 404
