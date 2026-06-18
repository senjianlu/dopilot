"""Tests for shared-token bearer auth on protected endpoints."""

from __future__ import annotations

from httpx import AsyncClient

from .conftest import TEST_TOKEN

TAIL = "/logs/tail?execution_id=e&attempt_id=a"


async def test_protected_requires_bearer_when_auth_on(client_auth: AsyncClient) -> None:
    resp = await client_auth.get(TAIL)
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "agent.unauthorized"
    assert body["message_key"] == "errors.unauthorized"
    assert body["detail"] == {}


async def test_protected_passes_auth_then_handler(client_auth: AsyncClient) -> None:
    resp = await client_auth.get(
        TAIL, headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    )
    # Correct token => passes auth and reaches the real handler, which reports
    # 404 because there is no state mapping for this attempt.
    assert resp.status_code == 404
    assert resp.json()["code"] == "agent.attempt_not_found"


async def test_wrong_token_rejected(client_auth: AsyncClient) -> None:
    resp = await client_auth.get(
        TAIL, headers={"Authorization": "Bearer wrong-token"}
    )
    assert resp.status_code == 401


async def test_no_auth_mode_skips_token(client: AsyncClient) -> None:
    # Empty shared token => auth OFF; protected endpoint reaches the handler
    # directly (404: no state mapping for this attempt).
    resp = await client.get(TAIL)
    assert resp.status_code == 404
    assert resp.json()["code"] == "agent.attempt_not_found"


async def test_run_requires_auth(client_auth: AsyncClient) -> None:
    # New /run endpoint is also behind the shared-token guard.
    resp = await client_auth.post(
        "/run",
        json={
            "execution_id": "e",
            "attempt_id": "a",
            "project": "demo",
            "spider": "phase1",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "agent.unauthorized"
