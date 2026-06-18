"""Tests for node selection: healthy + scrapy-capable, strategy-reduced."""

from __future__ import annotations

import uuid

import pytest
from dopilot_server.errors import ApiError
from dopilot_server.models.node import Node
from dopilot_server.nodes.service import pick_deploy_node, select_target_nodes


async def _node(session, agent_id, endpoint, *, status="healthy", scrapy=True):
    node = Node(
        id=uuid.uuid4(),
        agent_id=agent_id,
        endpoint=endpoint,
        status=status,
        capabilities={"scrapy": scrapy},
        health={},
    )
    session.add(node)
    await session.commit()
    return node


async def test_all_returns_every_healthy(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    await _node(db_session, "a2", "http://a2:6800")
    nodes = await select_target_nodes(db_session, "all")
    assert {n.agent_id for n in nodes} == {"a1", "a2"}


async def test_filters_unhealthy_and_non_scrapy(db_session):
    await _node(db_session, "a1", "http://a1:6800")
    await _node(db_session, "a2", "http://a2:6800", status="unhealthy")
    await _node(db_session, "a3", "http://a3:6800", scrapy=False)
    nodes = await select_target_nodes(db_session, "all")
    assert {n.agent_id for n in nodes} == {"a1"}


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


async def test_no_healthy_raises_409(db_session):
    await _node(db_session, "a1", "http://a1:6800", status="unhealthy")
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
