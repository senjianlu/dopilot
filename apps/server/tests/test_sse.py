"""Tests for SSE fan-out and the /logs/stream endpoint."""

from __future__ import annotations

import asyncio

from dopilot_server.logs import files
from dopilot_server.logs.sse import CLOSE, SubscriptionManager

# ---- SubscriptionManager unit ----


def test_subscribe_publish_fanout_and_hot():
    m = SubscriptionManager()
    q1 = m.subscribe("e")
    q2 = m.subscribe("e")
    assert m.subscriber_count("e") == 2
    assert m.hot_execution_ids() == {"e"}
    m.publish("e", {"type": "log", "end_offset": 5})
    assert q1.get_nowait()["end_offset"] == 5
    assert q2.get_nowait()["end_offset"] == 5
    m.unsubscribe("e", q1)
    assert m.subscriber_count("e") == 1
    m.unsubscribe("e", q2)
    assert m.hot_execution_ids() == set()


def test_close_sentinel():
    m = SubscriptionManager()
    q = m.subscribe("e")
    m.close("e")
    assert q.get_nowait() is CLOSE


# ---- endpoint ----
#
# We consume the SSE response inside a background task and run any "driver"
# (e.g. publish increments) concurrently. This is robust whether the ASGI
# transport streams incrementally or buffers the whole body: the app generator
# runs concurrently with the driver either way, so publishing during the stream
# never deadlocks the test coroutine.


async def _run_sse(client, url, *, headers=None, driver=None, timeout=6.0) -> str:
    chunks: list[str] = []

    async def consume():
        async with client.stream("GET", url, headers=headers or {}) as resp:
            assert resp.status_code == 200, resp.status_code
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for line in resp.aiter_lines():
                chunks.append(line)
                if line.startswith("event: complete"):
                    return

    task = asyncio.create_task(consume())
    try:
        if driver is not None:
            await driver()
        await asyncio.wait_for(task, timeout=timeout)
    finally:
        if not task.done():
            task.cancel()
    return "\n".join(chunks)


async def test_stream_backfill_then_complete(exec_client, seeder, db_session):
    """A terminal execution with body on disk: backfill history + complete."""
    execution, attempt, log_file = await seeder.running_execution()
    files.append(log_file.storage_path, b"phase1 demo spider started\n")
    log_file.size_bytes = files.size(log_file.storage_path)
    log_file.status = "complete"
    attempt.status = "finished"
    execution.status = "complete"
    await db_session.commit()

    url = f"/api/v1/executions/{execution.id}/logs/stream"
    text = await _run_sse(exec_client, url)
    assert "phase1 demo spider started" in text
    assert "event: complete" in text


async def test_stream_live_increment(
    exec_client, seeder, subscriptions, db_session
):
    execution, _attempt, _log = await seeder.running_execution()
    url = f"/api/v1/executions/{execution.id}/logs/stream"

    async def driver():
        for _ in range(300):
            if subscriptions.subscriber_count(execution.id) > 0:
                break
            await asyncio.sleep(0.01)
        subscriptions.publish(
            execution.id,
            {"type": "log", "start_offset": 0, "end_offset": 5, "content": "hi123"},
        )
        subscriptions.publish(
            execution.id, {"type": "complete", "status": "complete"}
        )

    text = await _run_sse(exec_client, url, driver=driver)
    assert "hi123" in text
    assert "event: complete" in text


async def test_normal_api_works_while_sse_stream_open(
    exec_client, seeder, subscriptions
):
    """P2 regression: an open SSE stream must NOT pin the request DB session;
    a normal DB-backed API call still works while the stream is open."""
    execution, _a, _l = await seeder.running_execution()
    url = f"/api/v1/executions/{execution.id}/logs/stream"

    async def driver():
        for _ in range(300):
            if subscriptions.subscriber_count(execution.id) > 0:
                break
            await asyncio.sleep(0.01)
        # A normal DB-backed endpoint must still succeed while the SSE is open.
        listing = await exec_client.get("/api/v1/executions")
        assert listing.status_code == 200
        subscriptions.publish(
            execution.id, {"type": "complete", "status": "complete"}
        )

    text = await _run_sse(exec_client, url, driver=driver)
    assert "event: complete" in text


async def test_stream_requires_token_when_auth_on(exec_client_auth_on, seeder):
    execution, _a, _l = await seeder.running_execution()
    r = await exec_client_auth_on.get(
        f"/api/v1/executions/{execution.id}/logs/stream"
    )
    assert r.status_code == 401
    assert r.json()["code"] == "auth.stream_unauthorized"


async def test_stream_token_flow_when_auth_on(
    exec_client_auth_on, seeder, db_session
):
    execution, attempt, log_file = await seeder.running_execution()
    files.append(log_file.storage_path, b"hello\n")
    log_file.size_bytes = files.size(log_file.storage_path)
    log_file.status = "complete"
    attempt.status = "finished"
    execution.status = "complete"
    await db_session.commit()

    login = await exec_client_auth_on.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "secret"}
    )
    token = login.json()["access_token"]
    issued = await exec_client_auth_on.post(
        f"/api/v1/executions/{execution.id}/logs/stream-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert issued.status_code == 200
    stream_token = issued.json()["stream_token"]

    url = (
        f"/api/v1/executions/{execution.id}/logs/stream"
        f"?stream_token={stream_token}"
    )
    text = await _run_sse(exec_client_auth_on, url)
    assert "hello" in text and "event: complete" in text


async def test_stream_token_not_required_when_auth_off(exec_client, seeder):
    execution, _a, _l = await seeder.running_execution()
    r = await exec_client.post(
        f"/api/v1/executions/{execution.id}/logs/stream-token"
    )
    assert r.status_code == 400
    assert r.json()["code"] == "auth.stream_token_not_required"
