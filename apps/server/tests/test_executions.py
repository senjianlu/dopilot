"""Execution endpoint tests: both phase-0 stubs return the 501 envelope."""

from __future__ import annotations


async def test_run_returns_501_envelope(client):
    resp = await client.post(
        "/api/v1/executions/run",
        json={"task_type": "scrapy", "target": "myspider"},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["code"] == "execution.not_implemented"
    assert body["message_key"] == "errors.notImplemented"
    assert body["detail"] == {"phase": 1}


async def test_logs_stream_returns_501_envelope(client):
    resp = await client.get("/api/v1/executions/abc-123/logs/stream")
    assert resp.status_code == 501
    body = resp.json()
    assert body["code"] == "logs.stream_not_implemented"
    assert body["message_key"] == "errors.notImplemented"
    assert body["detail"] == {"phase": 1}


async def test_run_unknown_task_type(client):
    resp = await client.post(
        "/api/v1/executions/run",
        json={"task_type": "bogus", "target": "x"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "execution.unknown_task_type"
