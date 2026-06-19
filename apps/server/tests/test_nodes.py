"""Node service tests (phase 1.5): heartbeat-sourced listing.

Liveness/health now comes from agent heartbeats (see test_heartbeat_api.py), not
a server-driven ``/health`` poll, so the old ``refresh_nodes`` is gone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dopilot_server.config.settings import Settings
from dopilot_server.models.node import Node
from dopilot_server.nodes.service import list_nodes


def _settings_with_agents(agents: list[str]) -> Settings:
    return Settings.model_validate({"nodes": {"agents": agents}})


async def test_list_nodes_shows_persisted_and_unknown(db_session):
    # a heartbeated node (persisted) ...
    db_session.add(
        Node(
            id=uuid.uuid4(),
            agent_id="agent-a",
            endpoint="agent-a:9100",
            status="healthy",
            capabilities={"scrapy": True},
            health={
                "redis": {
                    "connected": True,
                    "command_consumer": {"running": True},
                }
            },
            last_seen_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    # ... plus a configured-but-never-seen endpoint
    settings = _settings_with_agents(["agent-a:9100", "agent-never-seen:9100"])

    listed = await list_nodes(db_session, settings)
    by_endpoint = {n["endpoint"]: n for n in listed}
    assert by_endpoint["agent-a:9100"]["status"] == "healthy"
    assert by_endpoint["agent-a:9100"]["capabilities"]["scrapy"] is True
    assert by_endpoint["agent-never-seen:9100"]["status"] == "unknown"
    assert by_endpoint["agent-never-seen:9100"]["capabilities"] == {}


async def test_list_nodes_marks_missing_redis_detail_degraded(db_session):
    db_session.add(
        Node(
            id=uuid.uuid4(),
            agent_id="agent-a",
            endpoint="agent-a:9100",
            status="healthy",
            capabilities={"scrapy": True},
            health={},
            last_seen_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    listed = await list_nodes(db_session, _settings_with_agents([]))
    assert listed[0]["status"] == "degraded"


async def test_list_nodes_empty(db_session):
    settings = _settings_with_agents([])
    assert await list_nodes(db_session, settings) == []


async def test_get_nodes_endpoint_unknown(client):
    resp = await client.get("/api/v1/nodes")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": []}
