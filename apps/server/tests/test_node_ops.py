"""Phase 1.7.1: node scheduling-state (offline/online) + soft delete.

Covers the service-level filtering (offline/deleted nodes are not dispatch
candidates), the heartbeat-does-not-resurrect invariant, and the HTTP ops
endpoints.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from dopilot_protocol import AgentHeartbeatRequest
from dopilot_server.config.settings import Settings
from dopilot_server.errors import ApiError
from dopilot_server.models.node import Node
from dopilot_server.nodes.service import (
    list_nodes,
    offline_node,
    online_node,
    resolve_target_nodes,
    select_target_nodes,
    soft_delete_node,
    upsert_node_heartbeat,
)


def _heartbeat(agent_id: str, endpoint: str) -> AgentHeartbeatRequest:
    return AgentHeartbeatRequest.model_validate(
        {
            "agent_id": agent_id,
            "version": "0.1.0",
            "capabilities": {"scrapy": True},
            "detail": {
                "redis": {
                    "connected": True,
                    "command_consumer": {"running": True},
                }
            },
            "endpoint": endpoint,
            "reported_at": "2026-06-20T00:00:00Z",
        }
    )


async def _healthy_node(session, agent_id="a1", endpoint="http://a1:6800") -> Node:
    node = Node(
        id=uuid.uuid4(),
        agent_id=agent_id,
        endpoint=endpoint,
        status="healthy",
        capabilities={"scrapy": True},
        health={
            "redis": {"connected": True, "command_consumer": {"running": True}}
        },
        last_seen_at=datetime.now(UTC),
    )
    session.add(node)
    await session.commit()
    return node


async def test_offline_excludes_node_from_selection(db_session):
    node = await _healthy_node(db_session)
    # eligible before
    assert {n.agent_id for n in await select_target_nodes(db_session, "all")} == {
        "a1"
    }
    await offline_node(db_session, str(node.id))
    await db_session.commit()
    # excluded after offline, even though heartbeat health is still fresh
    selected, healthy = await resolve_target_nodes(db_session, "all")
    assert selected == []
    assert healthy == 0


async def test_online_restores_eligibility(db_session):
    node = await _healthy_node(db_session)
    await offline_node(db_session, str(node.id))
    await db_session.commit()
    await online_node(db_session, str(node.id))
    await db_session.commit()
    selected, healthy = await resolve_target_nodes(db_session, "all")
    assert {n.agent_id for n in selected} == {"a1"}
    assert healthy == 1


async def test_offline_sets_disabled_at_and_is_reversible(db_session):
    node = await _healthy_node(db_session)
    offlined = await offline_node(db_session, str(node.id))
    assert offlined.scheduling_enabled is False
    assert offlined.scheduling_disabled_at is not None
    onlined = await online_node(db_session, str(node.id))
    assert onlined.scheduling_enabled is True
    assert onlined.scheduling_disabled_at is None


async def test_soft_delete_excludes_node(db_session):
    node = await _healthy_node(db_session)
    deleted = await soft_delete_node(db_session, str(node.id))
    await db_session.commit()
    assert deleted.deleted_at is not None
    selected, healthy = await resolve_target_nodes(db_session, "all")
    assert selected == []
    assert healthy == 0


async def test_soft_deleted_node_still_listed(db_session):
    node = await _healthy_node(db_session)
    await soft_delete_node(db_session, str(node.id))
    await db_session.commit()
    listed = await list_nodes(db_session, Settings.model_validate({"nodes": {"agents": []}}))
    assert len(listed) == 1
    assert listed[0]["deleted_at"] is not None
    # health status remains visible (real heartbeat health, not "deleted")
    assert listed[0]["status"] == "healthy"


async def test_heartbeat_does_not_resurrect_deleted_node(db_session):
    node = await _healthy_node(db_session, agent_id="a1", endpoint="http://a1:6800")
    await soft_delete_node(db_session, str(node.id))
    await db_session.commit()

    refreshed = await upsert_node_heartbeat(
        db_session, "a1", _heartbeat("a1", "http://a1:6800")
    )
    await db_session.commit()
    # deleted_at survives the heartbeat; health fields still updated
    assert refreshed.deleted_at is not None
    assert refreshed.last_seen_at is not None
    # still excluded from selection
    selected, _ = await resolve_target_nodes(db_session, "all")
    assert selected == []


async def test_heartbeat_does_not_clear_offline_state(db_session):
    node = await _healthy_node(db_session, agent_id="a1", endpoint="http://a1:6800")
    await offline_node(db_session, str(node.id))
    await db_session.commit()
    refreshed = await upsert_node_heartbeat(
        db_session, "a1", _heartbeat("a1", "http://a1:6800")
    )
    await db_session.commit()
    assert refreshed.scheduling_enabled is False


async def test_get_node_404_for_bad_id(db_session):
    with pytest.raises(ApiError) as ei:
        await offline_node(db_session, "not-a-uuid")
    assert ei.value.status_code == 404
    assert ei.value.code == "node.not_found"


# ---- HTTP ops endpoints ----------------------------------------------------


async def test_offline_online_delete_endpoints(client, db_session):
    node = await _healthy_node(db_session)
    nid = str(node.id)

    r = await client.post(f"/api/v1/nodes/{nid}/offline")
    assert r.status_code == 200
    assert r.json()["scheduling_enabled"] is False

    r = await client.post(f"/api/v1/nodes/{nid}/online")
    assert r.status_code == 200
    assert r.json()["scheduling_enabled"] is True

    r = await client.delete(f"/api/v1/nodes/{nid}")
    assert r.status_code == 200
    assert r.json()["deleted_at"] is not None


async def test_offline_unknown_node_404(client):
    r = await client.post(f"/api/v1/nodes/{uuid.uuid4()}/offline")
    assert r.status_code == 404
    assert r.json()["code"] == "node.not_found"
