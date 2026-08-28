"""Task-list filters added for the schedule drill-down + target search.

Covers the two new ``list_tasks_page`` dimensions (``schedule_id`` and
``target_query``) at the service layer, and their ``GET /api/v1/tasks``
pass-through at the API layer. The API-layer cases exist on purpose: the
service tests alone would stay green if the endpoint forgot to forward a
parameter.
"""

from __future__ import annotations

from dopilot_protocol import ExecutionRunRequest
from dopilot_server.services import executions as svc
from dopilot_server.services import states


def _make_task(
    session,
    *,
    target: str,
    schedule_id: str | None = None,
    status: str = states.TASK_QUEUED,
    source: str | None = None,
):
    """Create one task row directly via the service (no nodes, no executions)."""
    req = ExecutionRunRequest(
        artifact_type="scrapy",
        target=target,
        node_strategy="all",
        params={},
    )
    if source is None:
        source = (
            states.TASK_SOURCE_TIMER if schedule_id else states.TASK_SOURCE_DIRECT
        )
    origin = svc.TaskOrigin(source=source, schedule_id=schedule_id)
    task = svc.create_task(session, req, origin)
    task.status = status
    return task


# --------------------------------------------------------------------------
# TC-01 .. TC-05: service layer
# --------------------------------------------------------------------------


async def test_list_tasks_page_schedule_filter(db_session):
    """TC-01: filtering by schedule_id returns only that schedule's tasks.

    Both a timer firing and a manual trigger-now stamp ``schedule_id``, so the
    drill-down must show both — the same "one schedule, one quota" framing the
    concurrency gate uses (decision 0022).
    """
    _make_task(
        db_session,
        target="demo:a",
        schedule_id="sch-a",
        source=states.TASK_SOURCE_TIMER,
    )
    _make_task(
        db_session,
        target="demo:b",
        schedule_id="sch-a",
        source=states.TASK_SOURCE_TRIGGER_NOW,
    )
    _make_task(db_session, target="demo:c", schedule_id="sch-b")
    _make_task(db_session, target="demo:d")  # direct run, no schedule
    await db_session.commit()

    rows, total = await svc.list_tasks_page(
        db_session, page=1, page_size=20, schedule_id="sch-a"
    )
    assert total == 2
    assert len(rows) == 2
    assert {t.schedule_id for t in rows} == {"sch-a"}
    assert {t.source for t in rows} == {
        states.TASK_SOURCE_TIMER,
        states.TASK_SOURCE_TRIGGER_NOW,
    }


async def test_target_query_is_case_insensitive_substring(db_session):
    """TC-02: target search matches a substring regardless of case."""
    _make_task(db_session, target="demo:Alpha")
    _make_task(db_session, target="demo:beta")
    _make_task(db_session, target="other:alpha")
    await db_session.commit()

    rows, total = await svc.list_tasks_page(
        db_session, page=1, page_size=20, target_query="ALPHA"
    )
    assert total == 2
    assert {t.target for t in rows} == {"demo:Alpha", "other:alpha"}

    rows, total = await svc.list_tasks_page(
        db_session, page=1, page_size=20, target_query="demo:"
    )
    assert total == 2
    assert {t.target for t in rows} == {"demo:Alpha", "demo:beta"}


async def test_filters_and_together(db_session):
    """TC-03: schedule_id + target_query + status AND, and total matches rows."""
    _make_task(
        db_session,
        target="demo:alpha",
        schedule_id="sch-a",
        status=states.TASK_COMPLETE,
    )
    _make_task(
        db_session,
        target="demo:alpha",
        schedule_id="sch-a",
        status=states.TASK_FAILED,
    )
    _make_task(
        db_session,
        target="demo:beta",
        schedule_id="sch-a",
        status=states.TASK_COMPLETE,
    )
    _make_task(
        db_session,
        target="demo:alpha",
        schedule_id="sch-b",
        status=states.TASK_COMPLETE,
    )
    await db_session.commit()

    rows, total = await svc.list_tasks_page(
        db_session,
        page=1,
        page_size=20,
        schedule_id="sch-a",
        target_query="alpha",
        status=states.TASK_COMPLETE,
    )
    # Exactly one row satisfies all three; total must agree with the row count,
    # which is what proves the count query carries the same WHERE clauses.
    assert total == 1
    assert len(rows) == total
    assert rows[0].target == "demo:alpha"
    assert rows[0].schedule_id == "sch-a"
    assert rows[0].status == states.TASK_COMPLETE


async def test_like_wildcards_are_escaped(db_session):
    """TC-04 (boundary): a user's % / _ / \\ match literally, not as wildcards."""
    for target in ("a%b", "a_b", "axb", "ayb", "a\\b"):
        _make_task(db_session, target=target)
    await db_session.commit()

    async def search(term: str) -> set[str]:
        rows, total = await svc.list_tasks_page(
            db_session, page=1, page_size=20, target_query=term
        )
        assert total == len(rows)
        return {t.target for t in rows}

    assert await search("%") == {"a%b"}
    assert await search("_") == {"a_b"}
    assert await search("a_b") == {"a_b"}
    assert await search("\\") == {"a\\b"}


async def test_blank_query_means_no_filter(db_session):
    """TC-05 (boundary): None/empty/whitespace disable the filter; terms strip."""
    _make_task(db_session, target="demo:alpha")
    _make_task(db_session, target="demo:beta")
    await db_session.commit()

    baseline, baseline_total = await svc.list_tasks_page(
        db_session, page=1, page_size=20
    )
    assert baseline_total == 2

    for blank in (None, "", "   "):
        rows, total = await svc.list_tasks_page(
            db_session, page=1, page_size=20, target_query=blank
        )
        assert total == baseline_total
        assert {t.id for t in rows} == {t.id for t in baseline}

    # A term with edge whitespace must behave exactly like the trimmed one:
    # the service strips before matching, so "  alpha  " is not searched
    # literally (which would match nothing).
    plain_rows, plain_total = await svc.list_tasks_page(
        db_session, page=1, page_size=20, target_query="alpha"
    )
    assert plain_total == 1
    assert plain_rows[0].target == "demo:alpha"

    padded_rows, padded_total = await svc.list_tasks_page(
        db_session, page=1, page_size=20, target_query="  alpha  "
    )
    assert padded_total == plain_total
    assert [t.id for t in padded_rows] == [t.id for t in plain_rows]


# --------------------------------------------------------------------------
# TC-06 .. TC-08: API layer pass-through
# --------------------------------------------------------------------------


async def test_get_tasks_schedule_filter(exec_client, db_session):
    """TC-06: ?schedule_id= filters; an unknown id is an empty page, not a 404."""
    _make_task(db_session, target="demo:a", schedule_id="sch-a")
    _make_task(db_session, target="demo:b", schedule_id="sch-b")
    await db_session.commit()

    res = await exec_client.get("/api/v1/tasks", params={"schedule_id": "sch-a"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert [t["target"] for t in body["tasks"]] == ["demo:a"]

    res = await exec_client.get(
        "/api/v1/tasks", params={"schedule_id": "does-not-exist"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 0
    assert body["tasks"] == []


async def test_get_tasks_target_query_filter(exec_client, db_session):
    """TC-07: ?q= reaches the service layer and ANDs with the other filters."""
    _make_task(db_session, target="demo:alpha", status=states.TASK_COMPLETE)
    _make_task(db_session, target="demo:beta", status=states.TASK_COMPLETE)
    _make_task(db_session, target="other:alpha", status=states.TASK_FAILED)
    await db_session.commit()

    res = await exec_client.get("/api/v1/tasks", params={"q": "alpha"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2
    assert {t["target"] for t in body["tasks"]} == {"demo:alpha", "other:alpha"}

    res = await exec_client.get(
        "/api/v1/tasks", params={"q": "alpha", "status": states.TASK_COMPLETE}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["tasks"][0]["target"] == "demo:alpha"

    # Whitespace-only input is not a filter at all.
    res = await exec_client.get("/api/v1/tasks", params={"q": "   "})
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 3


async def test_get_tasks_rejects_overlong_query(exec_client, db_session):
    """TC-08 (boundary): q over the cap is a 400 task.invalid_query; at cap is OK."""
    from dopilot_server.api.v1.tasks import MAX_TARGET_QUERY_LEN

    _make_task(db_session, target="demo:alpha")
    await db_session.commit()

    too_long = "a" * (MAX_TARGET_QUERY_LEN + 1)
    res = await exec_client.get("/api/v1/tasks", params={"q": too_long})
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "task.invalid_query"

    at_cap = "a" * MAX_TARGET_QUERY_LEN
    res = await exec_client.get("/api/v1/tasks", params={"q": at_cap})
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 0
