"""Node discovery + health-refresh service.

``refresh_nodes`` polls each configured agent ``/health`` endpoint and upserts
a :class:`Node` row (healthy/unhealthy). Upsert is done SELECT-then-update/insert
so it stays dialect-agnostic (no PostgreSQL ``ON CONFLICT``), which keeps the
SQLite test path working.

Outgoing requests carry ``Authorization: Bearer <shared_token>`` when the agent
shared token is configured.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..models.node import Node
from .strategy import NodeStrategy, reduce_nodes

_HTTP_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


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


def _normalize_endpoint(endpoint: str) -> str:
    """Return a base URL for an endpoint; assume http:// when no scheme given."""
    if endpoint.startswith(("http://", "https://")):
        return endpoint.rstrip("/")
    return f"http://{endpoint.rstrip('/')}"


def _auth_headers(settings: Settings) -> dict[str, str]:
    token = settings.agent_auth.shared_token
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


@contextlib.asynccontextmanager
async def _maybe_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as owned:
            yield owned


async def _get_node_by_endpoint(
    session: AsyncSession, endpoint: str
) -> Node | None:
    result = await session.execute(
        select(Node).where(Node.endpoint == endpoint)
    )
    return result.scalar_one_or_none()


def _node_to_dict(node: Node) -> dict[str, Any]:
    """Render a :class:`Node` as the frozen ``node`` JSON shape."""
    return {
        "id": str(node.id),
        "agent_id": node.agent_id,
        "endpoint": node.endpoint,
        "status": node.status,
        "capabilities": node.capabilities or {},
        "health": node.health or {},
        "last_seen_at": (
            node.last_seen_at.isoformat() if node.last_seen_at else None
        ),
    }


async def refresh_nodes(
    session: AsyncSession,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> list[Node]:
    """Poll every configured agent and upsert its health snapshot.

    Returns all node rows after the refresh.
    """
    headers = _auth_headers(settings)
    async with _maybe_client(client) as http:
        for endpoint in settings.nodes.agents:
            base = _normalize_endpoint(endpoint)
            agent_id: str | None = None
            capabilities: dict[str, Any] = {}
            health: dict[str, Any] = {}
            status = "unhealthy"
            try:
                resp = await http.get(f"{base}/health", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    agent_id = data.get("agent_id")
                    capabilities = data.get("capabilities") or {}
                    # agent health detail (phase 1: scrapyd subprocess status)
                    health = data.get("detail") or {}
                    status = "healthy"
            except Exception:  # noqa: BLE001 - any failure => unhealthy
                status = "unhealthy"

            node = await _get_node_by_endpoint(session, endpoint)
            now = datetime.now(UTC)
            if node is None:
                node = Node(endpoint=endpoint)
                session.add(node)
            node.status = status
            node.last_seen_at = now
            if status == "healthy":
                node.agent_id = agent_id
                node.capabilities = capabilities
                node.health = health
        await session.commit()

    result = await session.execute(select(Node))
    return list(result.scalars().all())


async def list_nodes(
    session: AsyncSession, settings: Settings
) -> list[dict[str, Any]]:
    """Return DB nodes plus any configured endpoint not yet persisted.

    Endpoints that have never been refreshed appear with status ``"unknown"``.
    """
    result = await session.execute(select(Node))
    rows = list(result.scalars().all())
    by_endpoint = {row.endpoint: row for row in rows}

    out: list[dict[str, Any]] = [_node_to_dict(row) for row in rows]
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
    session: AsyncSession, capability: str
) -> list[Node]:
    result = await session.execute(
        select(Node).where(Node.status == "healthy")
    )
    nodes = list(result.scalars().all())
    return [n for n in nodes if (n.capabilities or {}).get(capability)]


async def select_target_nodes(
    session: AsyncSession,
    strategy: str,
    node_ids: list[str] | None = None,
    *,
    capability: str = "scrapy",
) -> list[Node]:
    """Pick target nodes for an execution: only ``healthy`` + ``capability``.

    Applies the node strategy (all/random/selected) over the healthy set.
    Raises a structured 409 when no usable node exists so the caller never
    creates a half-baked running execution.
    """
    candidates = await _healthy_capable_nodes(session, capability)
    selected = reduce_nodes(_to_strategy(strategy), candidates, node_ids)
    if not selected:
        raise ApiError(
            409,
            "execution.no_healthy_nodes",
            "errors.noHealthyNodes",
            {
                "node_strategy": strategy,
                "node_ids": node_ids or [],
                "healthy_count": len(candidates),
            },
        )
    return selected


async def pick_deploy_node(
    session: AsyncSession,
    node_ids: list[str] | None = None,
    *,
    capability: str = "scrapy",
) -> Node:
    """Pick a single agent to deploy an egg to (specified first, else any)."""
    strategy = "selected" if node_ids else "all"
    nodes = await select_target_nodes(
        session, strategy, node_ids, capability=capability
    )
    return nodes[0]
