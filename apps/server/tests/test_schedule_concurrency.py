"""Schedule concurrency gate (decision 0022): validation + admission behaviour.

The gate lets at most ``max_concurrency`` of a schedule's tasks be ACTIVE at
once; ``0`` means unlimited. Timer firings and manual trigger-now share the one
quota. Row-lock serialization itself needs a real database and lives in
``test_schedule_concurrency_pg.py`` (SQLite compiles ``FOR UPDATE`` away).
"""

from __future__ import annotations

import logging

import pytest
from dopilot_server.config.settings import RedisSettings
from dopilot_server.models.execution import Execution, Task
from dopilot_server.models.notification import Notification
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services import states, templates
from dopilot_server.services.executions import list_tasks, new_id
from dopilot_server.services.outbox import create_run_outbox
from sqlalchemy import select


async def _template(client, seeder, **overrides) -> dict:
    artifact = await seeder.build_artifact()
    body = {
        "name": overrides.pop("name", "conc-template"),
        "build_artifact_id": artifact.id,
        "command": "scrapy crawl phase1",
        "node_strategy": "all",
    }
    body.update(overrides)
    r = await client.post("/api/v1/templates", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _schedule(client, template_id, **overrides) -> dict:
    body = {
        "name": overrides.pop("name", "conc-schedule"),
        "execution_template_id": template_id,
        "trigger_type": "interval",
        "interval_seconds": 30,
    }
    body.update(overrides)
    r = await client.post("/api/v1/schedules", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _trigger(client, schedule_id):
    return await client.post(f"/api/v1/schedules/{schedule_id}/trigger-now")


async def _seed_task(
    session,
    schedule_id: str,
    *,
    status: str,
    source: str = states.TASK_SOURCE_TIMER,
    executions: int = 0,
) -> Task:
    """Insert a task attributed to ``schedule_id`` in a chosen state."""
    task = Task(
        id=new_id(),
        artifact_type="scrapy",
        target="demo:phase1",
        status=status,
        params={},
        source=source,
        schedule_id=schedule_id,
        schedule_generation=0,
    )
    session.add(task)
    await session.flush()
    for i in range(executions):
        session.add(
            Execution(
                id=new_id(),
                task_id=task.id,
                agent_id=f"agent-{i}",
                status=states.EXEC_RUNNING,
                error_detail={},
            )
        )
    await session.commit()
    return task


async def _active_tasks(session, schedule_id: str) -> list[Task]:
    rows = await session.execute(
        select(Task).where(
            Task.schedule_id == schedule_id,
            Task.status.in_(states.TASK_ACTIVE),
        )
    )
    return list(rows.scalars().all())


# --- TC-01 / TC-02 / TC-03: value range + type contract ----------------------


async def test_max_concurrency_defaults_and_values(exec_client, seeder):
    template = await _template(exec_client, seeder)
    default = await _schedule(exec_client, template["id"], name="s-default")
    assert default["max_concurrency"] == 1

    for name, value in (("s-three", 3), ("s-zero", 0), ("s-max", 2147483647)):
        created = await _schedule(
            exec_client, template["id"], name=name, max_concurrency=value
        )
        assert created["max_concurrency"] == value


async def test_max_concurrency_invalid_inputs(exec_client, seeder, db_session):
    template = await _template(exec_client, seeder)

    # Out of range -> structured 400 from the service (NOT a DataError at commit).
    for value in (-1, 2147483648):
        r = await exec_client.post(
            "/api/v1/schedules",
            json={
                "name": f"bad-{value}",
                "execution_template_id": template["id"],
                "trigger_type": "interval",
                "interval_seconds": 30,
                "max_concurrency": value,
            },
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "schedule.invalid_max_concurrency"

    # Wrong type -> framework 422. Booleans included: Pydantic would otherwise
    # coerce false -> 0, which is the "unlimited" sentinel.
    for value in ("abc", 1.5, True, False):
        r = await exec_client.post(
            "/api/v1/schedules",
            json={
                "name": f"bad-{value}",
                "execution_template_id": template["id"],
                "trigger_type": "interval",
                "interval_seconds": 30,
                "max_concurrency": value,
            },
        )
        assert r.status_code == 422, f"{value!r} -> {r.status_code} {r.text}"

    # Direct service calls bypass the schema, so the service refuses too.
    tpl = await templates.get_template_or_404(db_session, template["id"])
    for value in (True, 2147483648):
        with pytest.raises(Exception) as exc:
            await sched_svc.create_schedule(
                db_session,
                {
                    "name": f"direct-{value}",
                    "execution_template_id": tpl.id,
                    "trigger_type": "interval",
                    "interval_seconds": 30,
                    "max_concurrency": value,
                },
            )
        assert getattr(exc.value, "status_code", None) == 400
        assert exc.value.code == "schedule.invalid_max_concurrency"


async def test_update_max_concurrency(exec_client, seeder, db_session):
    template = await _template(exec_client, seeder)
    schedule = await _schedule(exec_client, template["id"])

    ok = await exec_client.put(
        f"/api/v1/schedules/{schedule['id']}", json={"max_concurrency": 5}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["max_concurrency"] == 5

    for value in (-1, 2147483648):
        bad = await exec_client.put(
            f"/api/v1/schedules/{schedule['id']}", json={"max_concurrency": value}
        )
        assert bad.status_code == 400, bad.text
        assert bad.json()["code"] == "schedule.invalid_max_concurrency"

    # The UPDATE schema must reject bools as well; without its own validator a
    # PUT of false would land as 0 and quietly switch the gate off.
    for value in (True, False):
        bad = await exec_client.put(
            f"/api/v1/schedules/{schedule['id']}", json={"max_concurrency": value}
        )
        assert bad.status_code == 422, f"{value!r} -> {bad.status_code} {bad.text}"

    row = await sched_svc.get_schedule_or_404(db_session, schedule["id"])
    with pytest.raises(Exception) as exc:
        await sched_svc.update_schedule(db_session, row, {"max_concurrency": True})
    assert getattr(exc.value, "status_code", None) == 400


# --- TC-04..TC-09, TC-29: admission behaviour -------------------------------


async def test_limit_two_allows_two_then_rejects(exec_client, seeder, db_session):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(exec_client, template["id"], max_concurrency=2)

    first = await _trigger(exec_client, schedule["id"])
    second = await _trigger(exec_client, schedule["id"])
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    # Both must really occupy a slot: a no_target task is terminal at creation
    # and would make this test pass for the wrong reason.
    active = await _active_tasks(db_session, schedule["id"])
    assert len(active) == 2, [t.status for t in active]

    third = await _trigger(exec_client, schedule["id"])
    assert third.status_code == 409, third.text
    body = third.json()
    assert body["code"] == "schedule.concurrency_limit"
    assert body["detail"] == {"active": 2, "limit": 2}
    assert len(await _active_tasks(db_session, schedule["id"])) == 2


@pytest.mark.parametrize(
    "status", [states.TASK_QUEUED, states.TASK_RUNNING, states.TASK_FINALIZING]
)
async def test_all_active_statuses_count(exec_client, seeder, db_session, status):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(exec_client, template["id"], max_concurrency=1)
    await _seed_task(db_session, schedule["id"], status=status)

    r = await _trigger(exec_client, schedule["id"])
    assert r.status_code == 409, f"{status} -> {r.status_code} {r.text}"
    assert r.json()["detail"] == {"active": 1, "limit": 1}


@pytest.mark.parametrize(
    "status",
    [
        states.TASK_COMPLETE,
        states.TASK_FAILED,
        states.TASK_CANCELED,
        states.TASK_LOST,
        states.TASK_NO_TARGET,
    ],
)
async def test_terminal_statuses_release_slot(exec_client, seeder, db_session, status):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(exec_client, template["id"], max_concurrency=1)
    await _seed_task(db_session, schedule["id"], status=status)

    r = await _trigger(exec_client, schedule["id"])
    assert r.status_code == 200, f"{status} -> {r.status_code} {r.text}"
    assert len(await _active_tasks(db_session, schedule["id"])) == 1


async def test_zero_means_unlimited(exec_client, seeder, db_session):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(exec_client, template["id"], max_concurrency=0)
    await _seed_task(db_session, schedule["id"], status=states.TASK_RUNNING)
    await _seed_task(db_session, schedule["id"], status=states.TASK_RUNNING)

    for _ in range(2):
        r = await _trigger(exec_client, schedule["id"])
        assert r.status_code == 200, r.text
    assert len(await _active_tasks(db_session, schedule["id"])) == 4


async def test_count_scoped_to_own_schedule(exec_client, seeder, db_session):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    a = await _schedule(exec_client, template["id"], name="sched-a", max_concurrency=1)
    b = await _schedule(exec_client, template["id"], name="sched-b", max_concurrency=1)

    await _seed_task(db_session, b["id"], status=states.TASK_RUNNING)
    # A template run carries no schedule_id and must not be attributed to A.
    await _seed_task(
        db_session, None, status=states.TASK_RUNNING, source=states.TASK_SOURCE_TEMPLATE
    )

    r = await _trigger(exec_client, a["id"])
    assert r.status_code == 200, r.text


async def test_multi_execution_task_counts_once(exec_client, seeder, db_session):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(exec_client, template["id"], max_concurrency=2)
    # One task fanned out to two nodes: the quota is per TASK, not per execution.
    await _seed_task(
        db_session, schedule["id"], status=states.TASK_RUNNING, executions=2
    )

    r = await _trigger(exec_client, schedule["id"])
    assert r.status_code == 200, r.text


async def test_quota_shared_across_sources(
    exec_client, seeder, db_session, exec_settings, exec_redis, test_sessionmaker
):
    """Timer and trigger-now draw on ONE quota, in both directions."""
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)

    # (1) a timer-produced active task blocks a manual trigger
    timer_side = await _schedule(
        exec_client, template["id"], name="cross-a", max_concurrency=1
    )
    await _seed_task(
        db_session,
        timer_side["id"],
        status=states.TASK_RUNNING,
        source=states.TASK_SOURCE_TIMER,
    )
    blocked = await _trigger(exec_client, timer_side["id"])
    assert blocked.status_code == 409, blocked.text

    # (2) a trigger-now-produced active task blocks a timer firing
    manual_side = await _schedule(
        exec_client,
        template["id"],
        name="cross-b",
        max_concurrency=1,
        enabled=True,
    )
    await _seed_task(
        db_session,
        manual_side["id"],
        status=states.TASK_RUNNING,
        source=states.TASK_SOURCE_TRIGGER_NOW,
    )
    row = await sched_svc.get_schedule_or_404(db_session, manual_side["id"])
    dispatcher = CommandDispatcher(
        test_sessionmaker, CommandProducer(exec_redis, RedisSettings())
    )
    before = len(await list_tasks(db_session))
    res = await sched_svc.fire_timer(db_session, exec_settings, dispatcher, row)
    assert res is None
    assert len(await list_tasks(db_session)) == before


# --- TC-10 / TC-11: timer skip is silent, and reasons are not conflated ------


async def test_fire_timer_silently_skipped_when_full(
    exec_client,
    seeder,
    db_session,
    exec_settings,
    exec_redis,
    test_sessionmaker,
    caplog,
):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(
        exec_client, template["id"], max_concurrency=1, enabled=True
    )
    await _seed_task(db_session, schedule["id"], status=states.TASK_RUNNING)
    row = await sched_svc.get_schedule_or_404(db_session, schedule["id"])
    dispatcher = CommandDispatcher(
        test_sessionmaker, CommandProducer(exec_redis, RedisSettings())
    )
    before = len(await list_tasks(db_session))

    with caplog.at_level(logging.INFO, logger="dopilot_server.services.schedules"):
        res = await sched_svc.fire_timer(db_session, exec_settings, dispatcher, row)

    assert res is None
    assert len(await list_tasks(db_session)) == before
    await db_session.refresh(row)
    assert row.consecutive_error_count == 0
    notifications = (await db_session.execute(select(Notification))).scalars().all()
    assert notifications == []
    assert any(
        "timer firing skipped: concurrency 1/1" in r.getMessage()
        and schedule["id"] in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


@pytest.mark.parametrize("scenario", ["disabled", "backlog"])
async def test_non_concurrency_skips_do_not_log_limit(
    exec_client,
    seeder,
    db_session,
    exec_settings,
    exec_redis,
    test_sessionmaker,
    caplog,
    scenario,
):
    await seeder.healthy_node()
    template = await _template(exec_client, seeder)
    schedule = await _schedule(
        exec_client,
        template["id"],
        max_concurrency=5,  # plenty of headroom: never the concurrency branch
        enabled=(scenario == "backlog"),
    )
    if scenario == "backlog":
        task = await _seed_task(db_session, schedule["id"], status=states.TASK_QUEUED)
        create_run_outbox(
            db_session,
            task_id=task.id,
            execution_id=new_id(),
            agent_id="agent-1",
            payload={},
            manual=False,
        )
        await db_session.commit()

    slot = await sched_svc.acquire_firing_slot(
        db_session,
        schedule["id"],
        raise_on_full=False,
        require_enabled=True,
        coalesce_backlog=True,
    )
    assert slot.granted is False
    expected = (
        sched_svc.SKIP_DISABLED if scenario == "disabled" else sched_svc.SKIP_BACKLOG
    )
    assert slot.skip_reason == expected
    assert slot.active is None and slot.limit is None

    row = await sched_svc.get_schedule_or_404(db_session, schedule["id"])
    dispatcher = CommandDispatcher(
        test_sessionmaker, CommandProducer(exec_redis, RedisSettings())
    )
    before = len(await list_tasks(db_session))
    with caplog.at_level(logging.INFO, logger="dopilot_server.services.schedules"):
        res = await sched_svc.fire_timer(db_session, exec_settings, dispatcher, row)
    assert res is None
    assert len(await list_tasks(db_session)) == before
    assert not any(
        "timer firing skipped: concurrency" in r.getMessage() for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
