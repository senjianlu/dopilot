"""Tests for the unauthenticated /health endpoint."""

from __future__ import annotations

from pathlib import Path

from dopilot_agent.config.loader import get_settings
from dopilot_agent.main import create_app
from httpx import ASGITransport, AsyncClient

from .conftest import BASE_URL, make_settings


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


async def test_create_app_injects_settings_into_get_settings(workdir: Path) -> None:
    # Regression for phase 2.2.5: when create_app(settings) is given an explicit
    # settings object (as main() does with the baked default config), it must
    # wire that same object into the get_settings dependency. Otherwise request
    # handlers fall back to a bare load_settings() and raise ConfigError in an
    # agent container that omits DOPILOT_CONFIG. This test deliberately does NOT
    # use the conftest app builder, which masks the bug by manually overriding
    # get_settings after create_app().
    settings = make_settings(str(workdir), agent_token="")
    app = create_app(settings)

    assert app.dependency_overrides[get_settings]() is settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as ac:
        resp = await ac.get("/health")

    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "agent-test-1"
