"""Tests for node selection: heartbeat-live + scrapy-capable, strategy-reduced."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dopilot_server.errors import ApiError
from dopilot_server.models.node import Node
from dopilot_server.nodes.service import pick_deploy_node, select_target_nodes


async def _node(
    session,
    agent_id,
    endpoint,
    *,
    last_seen_age_seconds: float | None = 0.0,
    scrapy=True,
):
    # Phase 1.5: liveness is heartbeat recency. last_seen_age_seconds=None means
    # "never heartbeated" (last_seen_at NULL); a large age means "timed out".
    last_seen = (
        None
        if last_seen_age_seconds is None
        else datetime.now(UTC) - timedelta(seconds=last_seen_age_seconds)
    )
    node = Node(
        id=uuid.uuid4(),
        agent_id=agent_id,
        endpoint=endpoint,
        status="healthy",
        capabilities={"scrapy": scrapy},
        health={
            "redis": {
                "connected": True,
                "command_consumer": {"running": True},
            }
        },
        last_seen_at=last_seen,
    )
    session.add(node)
    await session.commit()
    return node


async def test_all_returns_every_live(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    await _node(db_session, "a2", "http://a2:6800")
    nodes = await select_target_nodes(db_session, "all")
    assert {n.agent_id for n in nodes} == {"a1", "a2"}


async def test_filters_stale_never_seen_and_non_scrapy(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    # heartbeat-timed-out (well past the 30s default window)
    await _node(db_session, "a2", "http://a2:6800", last_seen_age_seconds=120)
    # never heartbeated
    await _node(db_session, "a4", "http://a4:6800", last_seen_age_seconds=None)
    # live but not scrapy-capable
    await _node(db_session, "a3", "http://a3:6800", scrapy=False)
    nodes = await select_target_nodes(db_session, "all")
    assert {n.agent_id for n in nodes} == {"a1"}


async def test_heartbeat_timeout_boundary(db_session):
    # within the window -> selectable; past it -> not. Use an explicit timeout.
    await _node(db_session, "fresh", "http://fresh:6800", last_seen_age_seconds=5)
    await _node(db_session, "stale", "http://stale:6800", last_seen_age_seconds=40)
    nodes = await select_target_nodes(db_session, "all", timeout_seconds=10)
    assert {n.agent_id for n in nodes} == {"fresh"}


async def test_random_returns_one(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    await _node(db_session, "a2", "http://a2:6800")
    nodes = await select_target_nodes(db_session, "random")
    assert len(nodes) == 1


async def test_selected_by_agent_id(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    await _node(db_session, "a2", "http://a2:6800")
    nodes = await select_target_nodes(db_session, "selected", ["a2"])
    assert {n.agent_id for n in nodes} == {"a2"}


async def test_selected_by_node_id(db_session):
    n1 = await _node(db_session, "a1", "http://a1:6800")
    await _node(db_session, "a2", "http://a2:6800")
    nodes = await select_target_nodes(db_session, "selected", [str(n1.id)])
    assert {n.agent_id for n in nodes} == {"a1"}


async def test_no_live_node_raises_409(db_session):
    await _node(db_session, "a1", "http://a1:6800", last_seen_age_seconds=300)
    with pytest.raises(ApiError) as ei:
        await select_target_nodes(db_session, "all")
    assert ei.value.status_code == 409
    assert ei.value.code == "execution.no_healthy_nodes"


async def test_selected_none_match_raises(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    with pytest.raises(ApiError) as ei:
        await select_target_nodes(db_session, "selected", ["nope"])
    assert ei.value.code == "execution.no_healthy_nodes"


async def test_invalid_strategy_raises(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    with pytest.raises(ApiError) as ei:
        await select_target_nodes(db_session, "weird")
    assert ei.value.code == "execution.invalid_node_strategy"


async def test_pick_deploy_node(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    node = await pick_deploy_node(db_session)
    assert node.agent_id == "a1"


async def test_missing_redis_detail_is_not_selectable(db_session):
    node = await _node(db_session, "a1", "http://a1:6800")
    node.health = {}
    await db_session.commit()
    with pytest.raises(ApiError) as ei:
        await select_target_nodes(db_session, "all")
    assert ei.value.code == "execution.no_healthy_nodes"


async def test_disconnected_redis_detail_is_not_selectable(db_session):
    node = await _node(db_session, "a1", "http://a1:6800")
    node.health = {
        "redis": {
            "connected": False,
            "command_consumer": {"running": True},
        }
    }
    await db_session.commit()
    with pytest.raises(ApiError) as ei:
        await select_target_nodes(db_session, "all")
    assert ei.value.code == "execution.no_healthy_nodes"
