"""Tests for the unauthenticated /health endpoint."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health_shape(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "dopilot-agent"
    assert body["agent_id"] == "agent-test-1"
    assert body["workdir"] == "/agent-data/test"
    assert body["capabilities"] == {
        "scrapy": True,
        "script": True,
        "docker": False,
    }


async def test_health_no_token_required_when_auth_on(client_auth: AsyncClient) -> None:
    # Even with shared-token auth enabled, /health must not require a token.
    resp = await client_auth.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "dopilot-agent"
