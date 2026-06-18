"""Node service tests: healthy/unhealthy refresh and unknown-endpoint listing."""

from __future__ import annotations

import httpx
from dopilot_server.config.settings import Settings
from dopilot_server.nodes.service import list_nodes, refresh_nodes


def _settings_with_agents(agents: list[str]) -> Settings:
    return Settings.model_validate({"nodes": {"agents": agents}})


async def test_refresh_marks_healthy(db_session):
    settings = _settings_with_agents(["agent-a:9100"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "dopilot-agent",
                "version": "0.0.0",
                "agent_id": "agent-a",
                "capabilities": {
                    "scrapy": True,
                    "script": False,
                    "docker": False,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        nodes = await refresh_nodes(db_session, settings, client=client)

    assert len(nodes) == 1
    node = nodes[0]
    assert node.status == "healthy"
    assert node.agent_id == "agent-a"
    assert node.capabilities["scrapy"] is True
    assert node.last_seen_at is not None


async def test_refresh_marks_unhealthy_on_error(db_session):
    settings = _settings_with_agents(["agent-b:9100"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="kaboom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        nodes = await refresh_nodes(db_session, settings, client=client)

    assert nodes[0].status == "unhealthy"


async def test_refresh_marks_unhealthy_on_exception(db_session):
    settings = _settings_with_agents(["agent-c:9100"])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        nodes = await refresh_nodes(db_session, settings, client=client)

    assert nodes[0].status == "unhealthy"


async def test_list_nodes_shows_unknown(db_session):
    settings = _settings_with_agents(["agent-never-seen:9100"])
    listed = await list_nodes(db_session, settings)
    assert len(listed) == 1
    assert listed[0]["endpoint"] == "agent-never-seen:9100"
    assert listed[0]["status"] == "unknown"
    assert listed[0]["capabilities"] == {}


async def test_get_nodes_endpoint_unknown(client):
    # The auth-off client uses empty agents by default; configure via override.
    resp = await client.get("/api/v1/nodes")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": []}
