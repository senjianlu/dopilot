"""Node service: heartbeat upsert, listing, and target selection.

Phase 1.5: node liveness/health/capabilities are written by agent heartbeats
(:func:`upsert_node_heartbeat`), NOT a server-driven ``/health`` poll. Selection
filters by heartbeat recency. Upserts are SELECT-then-update/insert so they stay
dialect-agnostic (no PostgreSQL ``ON CONFLICT``), keeping the SQLite test path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from dopilot_protocol import AgentHeartbeatRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..models.node import Node
from .strategy import NodeStrategy, reduce_nodes

# Fallback heartbeat-liveness window when a caller does not thread the configured
# [agents].heartbeat_timeout_seconds (mirrors the AgentsSettings default).
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 30


def _to_strategy(strategy: str) -> NodeStrategy:
    """Map the web ``node_strategy`` string onto :class:`NodeStrategy`.

    The web uses ``selected``; the seam enum calls it ``specified``.
    """
    if strategy in ("selected", "specified"):
        return NodeStrategy.SPECIFIED
    if strategy == "random":
        return NodeStrategy.RANDOM
    if strategy == "all":
        return NodeStrategy.ALL
    raise ApiError(
        400,
        "execution.invalid_node_strategy",
        "errors.invalidNodeStrategy",
        {"node_strategy": strategy},
    )


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _heartbeat_fresh(
    node: Node, *, now: datetime, timeout_seconds: int
) -> bool:
    if node.last_seen_at is None:
        return False
    return _as_aware(node.last_seen_at) >= now - timedelta(seconds=timeout_seconds)


def _redis_transport_healthy(health: dict[str, Any] | None) -> bool:
    redis = (health or {}).get("redis")
    if not isinstance(redis, dict):
        return False
    command = redis.get("command_consumer")
    return (
        redis.get("connected") is True
        and isinstance(command, dict)
        and command.get("running") is True
    )


def _aggregate_node_status(
    node: Node, *, now: datetime, timeout_seconds: int
) -> str:
    if not _heartbeat_fresh(node, now=now, timeout_seconds=timeout_seconds):
        return "unknown" if node.last_seen_at is None else "unhealthy"
    if not _redis_transport_healthy(node.health):
        return "degraded"
    return "healthy"


async def _get_node_by_endpoint(
    session: AsyncSession, endpoint: str
) -> Node | None:
    result = await session.execute(
        select(Node).where(Node.endpoint == endpoint)
    )
    return result.scalar_one_or_none()


def _node_to_dict(
    node: Node, *, now: datetime, timeout_seconds: int
) -> dict[str, Any]:
    """Render a :class:`Node` as the frozen ``node`` JSON shape."""
    return {
        "id": str(node.id),
        "agent_id": node.agent_id,
        "endpoint": node.endpoint,
        "status": _aggregate_node_status(
            node, now=now, timeout_seconds=timeout_seconds
        ),
        "capabilities": node.capabilities or {},
        "health": node.health or {},
        "last_seen_at": (
            node.last_seen_at.isoformat() if node.last_seen_at else None
        ),
    }


async def _get_node_by_agent_id(
    session: AsyncSession, agent_id: str
) -> Node | None:
    result = await session.execute(
        select(Node).where(Node.agent_id == agent_id)
    )
    return result.scalar_one_or_none()


async def upsert_node_heartbeat(
    session: AsyncSession, agent_id: str, hb: AgentHeartbeatRequest
) -> Node:
    """Apply an agent heartbeat: refresh ``last_seen_at`` + capabilities/health.

    Phase 1.5: this REPLACES server polling of agent ``/health`` as the source
    of ``nodes.last_seen_at``. Keyed by ``agent_id``; matched first by agent_id,
    then by the agent-advertised endpoint, so a node previously seeded by
    endpoint is adopted rather than duplicated. The caller commits.
    """
    now = datetime.now(UTC)
    node = await _get_node_by_agent_id(session, agent_id)
    if node is None and hb.endpoint:
        # Adopt a node previously created from config/discovery by endpoint.
        node = await _get_node_by_endpoint(session, hb.endpoint)
    if node is None:
        node = Node(endpoint=hb.endpoint or f"agent://{agent_id}")
        session.add(node)

    node.agent_id = agent_id
    if hb.endpoint:
        node.endpoint = hb.endpoint
    node.last_seen_at = now
    node.capabilities = hb.capabilities.model_dump()
    node.health = dict(hb.detail or {})
    node.status = _aggregate_node_status(
        node, now=now, timeout_seconds=DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
    )
    return node


async def list_nodes(
    session: AsyncSession, settings: Settings
) -> list[dict[str, Any]]:
    """Return DB nodes plus any configured endpoint not yet persisted.

    Endpoints that have never been refreshed appear with status ``"unknown"``.
    """
    result = await session.execute(select(Node))
    rows = list(result.scalars().all())
    by_endpoint = {row.endpoint: row for row in rows}

    now = datetime.now(UTC)
    timeout_seconds = settings.agents.heartbeat_timeout_seconds
    out: list[dict[str, Any]] = [
        _node_to_dict(row, now=now, timeout_seconds=timeout_seconds)
        for row in rows
    ]
    for endpoint in settings.nodes.agents:
        if endpoint not in by_endpoint:
            out.append(
                {
                    "id": None,
                    "agent_id": None,
                    "endpoint": endpoint,
                    "status": "unknown",
                    "capabilities": {},
                    "health": {},
                    "last_seen_at": None,
                }
            )
    return out


async def _healthy_capable_nodes(
    session: AsyncSession,
    capability: str,
    *,
    timeout_seconds: int,
) -> list[Node]:
    """Nodes that heartbeated within ``timeout_seconds`` and have ``capability``.

    Phase 1.5: liveness is ``now - last_seen_at <= timeout_seconds`` (agent
    heartbeat), NOT the old poll-written ``status == "healthy"``. Nodes that
    never heartbeated (``last_seen_at`` NULL) are excluded.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=timeout_seconds)
    result = await session.execute(
        select(Node).where(Node.last_seen_at >= cutoff)
    )
    nodes = list(result.scalars().all())
    return [
        n for n in nodes
        if (n.capabilities or {}).get(capability)
        and _aggregate_node_status(
            n, now=now, timeout_seconds=timeout_seconds
        ) == "healthy"
    ]


async def resolve_target_nodes(
    session: AsyncSession,
    strategy: str,
    node_ids: list[str] | None = None,
    *,
    capability: str = "scrapy",
    timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
) -> tuple[list[Node], int]:
    """Pick target nodes for a task; NEVER raise on the zero-node case.

    Returns ``(selected_nodes, healthy_candidate_count)``. Phase 1.7 packet 2:
    the caller (task dispatch) creates the task FIRST, then persists a terminal
    ``no_target`` task when ``selected_nodes`` is empty — it does not raise a
    409. ``_to_strategy`` still validates the strategy string (400 on garbage).
    """
    candidates = await _healthy_capable_nodes(
        session, capability, timeout_seconds=timeout_seconds
    )
    selected = reduce_nodes(_to_strategy(strategy), candidates, node_ids)
    return selected, len(candidates)


async def select_target_nodes(
    session: AsyncSession,
    strategy: str,
    node_ids: list[str] | None = None,
    *,
    capability: str = "scrapy",
    timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
) -> list[Node]:
    """Pick target nodes for an execution: heartbeat-live + ``capability``.

    Applies the node strategy (all/random/selected) over the live set. Raises a
    structured 409 when no usable node exists so the caller never creates a
    half-baked running execution. (Task dispatch uses the non-raising
    :func:`resolve_target_nodes` + ``no_target``; this 409 path remains for egg
    deploy, which has no task to mark.)
    """
    selected, healthy_count = await resolve_target_nodes(
        session, strategy, node_ids,
        capability=capability, timeout_seconds=timeout_seconds,
    )
    if not selected:
        raise ApiError(
            409,
            "execution.no_healthy_nodes",
            "errors.noHealthyNodes",
            {
                "node_strategy": strategy,
                "node_ids": node_ids or [],
                "healthy_count": healthy_count,
            },
        )
    return selected


async def pick_deploy_node(
    session: AsyncSession,
    node_ids: list[str] | None = None,
    *,
    capability: str = "scrapy",
    timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
) -> Node:
    """Pick a single agent to deploy an egg to (specified first, else any)."""
    strategy = "selected" if node_ids else "all"
    nodes = await select_target_nodes(
        session, strategy, node_ids, capability=capability,
        timeout_seconds=timeout_seconds,
    )
    return nodes[0]
