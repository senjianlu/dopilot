"""Tests for the phase-0 stub endpoints and query validation."""

from __future__ import annotations

from httpx import AsyncClient


async def test_status_501(client: AsyncClient) -> None:
    resp = await client.get("/status")
    assert resp.status_code == 501
    body = resp.json()
    assert body["code"] == "status.not_implemented"
    assert body["message_key"] == "errors.notImplemented"


async def test_cleanup_post_501(client: AsyncClient) -> None:
    resp = await client.post("/executions/attempt-123/logs/cleanup")
    assert resp.status_code == 501
    assert resp.json()["code"] == "logs.cleanup_not_implemented"


async def test_tail_missing_required_params_422(client: AsyncClient) -> None:
    # No execution_id / attempt_id => FastAPI query validation error.
    resp = await client.get("/logs/tail")
    assert resp.status_code == 422


async def test_tail_with_required_params_501(client: AsyncClient) -> None:
    resp = await client.get("/logs/tail?execution_id=e&attempt_id=a")
    assert resp.status_code == 501
    assert resp.json()["detail"] == {"phase": 1}
