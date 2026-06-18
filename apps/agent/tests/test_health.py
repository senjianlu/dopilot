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
    # workdir is the test tmp dir wired by the conftest fixture.
    assert body["workdir"].endswith("agent-data")
    assert body["capabilities"] == {
        "scrapy": True,
        "script": True,
        "docker": False,
    }


async def test_health_includes_scrapyd_detail(client: AsyncClient) -> None:
    # /health merges a non-protocol detail.scrapyd block with the subprocess
    # health. Tests run with [scrapyd].start = false so no child is managed.
    resp = await client.get("/health")
    assert resp.status_code == 200

    detail = resp.json()["detail"]
    assert "scrapyd" in detail
    scrapyd = detail["scrapyd"]
    assert scrapyd["running"] is False
    assert scrapyd["port"] == 6801
    assert scrapyd["pid"] is None


async def test_health_no_token_required_when_auth_on(client_auth: AsyncClient) -> None:
    # Even with shared-token auth enabled, /health must not require a token.
    resp = await client_auth.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "dopilot-agent"
