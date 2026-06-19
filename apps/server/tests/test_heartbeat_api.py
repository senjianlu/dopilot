"""Heartbeat endpoint + agent->server auth dependency tests (phase 1.5)."""

from __future__ import annotations

import pytest
from dopilot_server.auth.agent_dependencies import require_server_token
from dopilot_server.config.settings import Settings
from dopilot_server.errors import ApiError
from dopilot_server.models.node import Node
from sqlalchemy import select
from starlette.requests import Request


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "method": "POST", "path": "/"})


def _heartbeat_body(agent_id: str = "agent-1") -> dict:
    return {
        "agent_id": agent_id,
        "version": "0.1.0",
        "capabilities": {"scrapy": True, "script": False, "docker": False},
        "load": {"running_attempts": 2},
        "detail": {"scrapyd": {"port": 6801, "managed": True}},
        "endpoint": "agent:6800",
        "reported_at": "2026-06-19T00:00:00Z",
    }


async def test_heartbeat_upserts_node(client, db_session):
    resp = await client.post(
        "/api/v1/agents/agent-1/heartbeat", json=_heartbeat_body("agent-1")
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    node = (
        await db_session.execute(select(Node).where(Node.agent_id == "agent-1"))
    ).scalar_one()
    assert node.status == "healthy"
    assert node.last_seen_at is not None
    assert node.capabilities["scrapy"] is True
    assert node.endpoint == "agent:6800"
    assert node.health == {"scrapyd": {"port": 6801, "managed": True}}


async def test_heartbeat_second_call_refreshes(client, db_session):
    await client.post("/api/v1/agents/agent-1/heartbeat", json=_heartbeat_body())
    # second heartbeat updates the same row (keyed by agent_id, no duplicate)
    await client.post("/api/v1/agents/agent-1/heartbeat", json=_heartbeat_body())
    rows = (
        (await db_session.execute(select(Node).where(Node.agent_id == "agent-1")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].last_seen_at is not None


async def test_heartbeat_id_mismatch_400(client):
    resp = await client.post(
        "/api/v1/agents/other/heartbeat", json=_heartbeat_body("agent-1")
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "agent.heartbeat_id_mismatch"


async def test_require_server_token_off_allows_anything():
    settings = Settings.model_validate({})  # no [agents].server_shared_token
    assert settings.agents.inbound_auth_enabled is False
    # no exception regardless of header
    await require_server_token(_request({}), settings)
    await require_server_token(_request({"authorization": "Bearer whatever"}), settings)


async def test_require_server_token_on_enforces():
    settings = Settings.model_validate(
        {"agents": {"server_shared_token": "s3cret"}}
    )
    assert settings.agents.inbound_auth_enabled is True
    # missing token
    with pytest.raises(ApiError) as ei:
        await require_server_token(_request({}), settings)
    assert ei.value.status_code == 401
    # wrong token
    with pytest.raises(ApiError):
        await require_server_token(
            _request({"authorization": "Bearer nope"}), settings
        )
    # correct token passes
    await require_server_token(
        _request({"authorization": "Bearer s3cret"}), settings
    )
