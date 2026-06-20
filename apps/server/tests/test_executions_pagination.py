"""Phase 1.8: tasks-list backend pagination + spider filter + stats.

Also covers the aggregate (non-N+1) child-count path and the all-selected-
unschedulable template run -> ``no_target`` task path.
"""

from __future__ import annotations

import hashlib

from dopilot_protocol import ExecutionRunRequest
from dopilot_server.services import executions as svc
from dopilot_server.services import states


async def _run_artifact(exec_client, seeder, spider: str):
    """Run a seeded artifact via a command-first execution template.

    The artifact must advertise ``spider`` so server-side spider-membership
    validation accepts ``scrapy crawl <spider>``. Each spider gets a distinct
    content hash so the seeder does not dedupe distinct spiders onto one
    artifact.
    """
    artifact = await seeder.build_artifact(
        spiders=(spider,),
        sha256=hashlib.sha256(spider.encode()).hexdigest(),
    )
    tpl = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": f"t-{spider}",
            "build_artifact_id": artifact.id,
            "command": f"scrapy crawl {spider}",
            "node_strategy": "all",
        },
    )
    assert tpl.status_code == 200, tpl.text
    return await exec_client.post(f"/api/v1/templates/{tpl.json()['id']}/run")


async def _seed_tasks(session, settings, specs):
    """Create tasks (with N child executions) directly via the service."""
    from dopilot_server.models.node import Node

    created = []
    node_seq = 0
    for spider, n_children in specs:
        req = ExecutionRunRequest(
            artifact_type="scrapy",
            target=f"demo:{spider}",
            node_strategy="all",
            params={"project": "demo", "spider": spider},
        )
        task = svc.create_task(session, req)
        for _ in range(n_children):
            node = Node(endpoint=f"http://x{node_seq}:6800", agent_id=f"x{node_seq}")
            node_seq += 1
            session.add(node)
            await session.flush()
            svc.create_execution(session, task, node)
        created.append(task)
    await session.commit()
    return created


async def test_create_task_copies_spider(db_session):
    req = ExecutionRunRequest(
        artifact_type="scrapy",
        target="demo:s1",
        node_strategy="all",
        params={"project": "demo", "spider": "s1"},
    )
    task = svc.create_task(db_session, req)
    await db_session.commit()
    assert task.spider == "s1"


async def test_list_tasks_page_paginates_and_counts_total(db_session, exec_settings):
    await _seed_tasks(db_session, exec_settings, [("s1", 0)] * 25)
    page1, total = await svc.list_tasks_page(db_session, page=1, page_size=10)
    assert total == 25
    assert len(page1) == 10
    page3, _ = await svc.list_tasks_page(db_session, page=3, page_size=10)
    assert len(page3) == 5


async def test_list_tasks_page_spider_filter(db_session, exec_settings):
    await _seed_tasks(db_session, exec_settings, [("alpha", 0), ("beta", 0), ("alpha", 0)])
    rows, total = await svc.list_tasks_page(
        db_session, page=1, page_size=20, spider="alpha"
    )
    assert total == 2
    assert {t.spider for t in rows} == {"alpha"}


async def test_child_execution_counts_aggregate(db_session, exec_settings):
    tasks = await _seed_tasks(db_session, exec_settings, [("s1", 2), ("s2", 0), ("s3", 3)])
    counts = await svc.child_execution_counts(db_session, [t.id for t in tasks])
    by_spider = {t.spider: counts[t.id] for t in tasks}
    assert by_spider == {"s1": 2, "s2": 0, "s3": 3}


async def test_list_task_spiders_distinct(db_session, exec_settings):
    await _seed_tasks(db_session, exec_settings, [("a", 0), ("b", 0), ("a", 0)])
    assert await svc.list_task_spiders(db_session) == ["a", "b"]


# ---- HTTP surface ----------------------------------------------------------


async def test_get_tasks_validates_page_size(exec_client, seeder):
    await seeder.healthy_node()
    r = await exec_client.get("/api/v1/tasks?page=1&page_size=7")
    assert r.status_code == 400
    assert r.json()["code"] == "task.invalid_page_size"


async def test_get_tasks_returns_pagination_envelope(exec_client, seeder):
    await _run_artifact(exec_client, seeder, "phase1")
    r = await exec_client.get("/api/v1/tasks?page=1&page_size=20")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"tasks", "page", "page_size", "total", "spiders"}
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] >= 1


async def test_get_tasks_spider_filter(exec_client, seeder):
    await seeder.healthy_node()
    await _run_artifact(exec_client, seeder, "alpha")
    await _run_artifact(exec_client, seeder, "beta")
    r = await exec_client.get("/api/v1/tasks?page=1&page_size=20&spider=alpha")
    body = r.json()
    assert body["total"] == 1
    assert all(row["spider"] == "alpha" for row in body["tasks"])
    # known spider values surfaced for the filter dropdown
    assert set(body["spiders"]) == {"alpha", "beta"}


async def test_get_tasks_invalid_page_400(exec_client):
    r = await exec_client.get("/api/v1/tasks?page=0&page_size=20")
    assert r.status_code == 422  # FastAPI ge=1 validation


# ---- template run with all selected nodes unschedulable -> no_target -------


async def test_selected_template_all_unschedulable_creates_no_target(
    exec_client, seeder, db_session
):
    # one healthy node, then offline it: a selected template referencing it has
    # no schedulable target and must produce a visible no_target task.
    node = await seeder.healthy_node(agent_id="a1")
    from dopilot_server.nodes.service import offline_node

    await offline_node(db_session, str(node.id))
    await db_session.commit()

    artifact = await seeder.build_artifact()
    tpl = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "sel",
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1",
            "node_strategy": "selected",
            "node_ids": [str(node.id)],
        },
    )
    assert tpl.status_code == 200, tpl.text
    run = await exec_client.post(f"/api/v1/templates/{tpl.json()['id']}/run")
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == states.TASK_NO_TARGET
