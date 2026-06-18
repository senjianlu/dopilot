"""Tests for endpoint wiring and query validation (real phase-1 behavior).

These replace the phase-0 501-stub expectations: /status, /logs/tail, and the
cleanup endpoint now have real behavior. They still assert the param-validation
contract (missing required query params => 422).
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_status_requires_params(client: AsyncClient) -> None:
    # execution_id / attempt_id are required query params now.
    resp = await client.get("/status")
    assert resp.status_code == 422


async def test_status_unknown_attempt_is_200(client: AsyncClient) -> None:
    # No state file for this attempt => status=unknown, HTTP 200 (so the server
    # can mark the attempt lost rather than retry forever).
    resp = await client.get("/status?execution_id=e&attempt_id=missing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unknown"
    assert body["attempt_id"] == "missing"


async def test_cleanup_unknown_attempt_idempotent(client: AsyncClient) -> None:
    # Cleaning up an attempt with no log/state removes nothing, but is not an
    # error and is safe to call repeatedly.
    resp = await client.post("/executions/attempt-123/logs/cleanup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempt_id"] == "attempt-123"
    assert body["removed"] is False


async def test_tail_missing_required_params_422(client: AsyncClient) -> None:
    # No execution_id / attempt_id => FastAPI query validation error.
    resp = await client.get("/logs/tail")
    assert resp.status_code == 422


async def test_tail_unknown_attempt_404(client: AsyncClient) -> None:
    # With params but no state mapping => 404 agent.attempt_not_found.
    resp = await client.get("/logs/tail?execution_id=e&attempt_id=a")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "agent.attempt_not_found"
