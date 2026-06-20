"""Node endpoints: list known nodes + scheduling-state / soft-delete ops.

Phase 1.5: node liveness/health is sourced from agent heartbeats
(``POST /api/v1/agents/{agent_id}/heartbeat``), not a server-driven ``/health``
poll, so the old ``POST /nodes/refresh`` is gone — the web "refresh" button just
re-issues ``GET /nodes``.

Phase 1.7.1: a node can be taken offline/online (reversible scheduling state)
and soft-deleted. Offline/deleted nodes still receive heartbeats and show real
health, but are excluded from dispatch target selection. Delete is a soft
delete; the row stays for historical references and is never resurrected by a
later heartbeat.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...nodes.service import (
    list_nodes,
    node_view,
    offline_node,
    online_node,
    soft_delete_node,
)
from .schemas import NodesResponse, NodeView

router = APIRouter(tags=["nodes"])


@router.get("/nodes", response_model=NodesResponse)
async def get_nodes(
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> NodesResponse:
    """Return persisted nodes plus configured-but-unseen endpoints (unknown)."""
    nodes = await list_nodes(session, settings)
    return NodesResponse(nodes=[NodeView(**n) for n in nodes])


@router.post("/nodes/{node_id}/offline", response_model=NodeView)
async def post_node_offline(
    node_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> NodeView:
    """Take a node offline (reversible). Excluded from dispatch selection."""
    node = await offline_node(session, node_id)
    await session.commit()
    await session.refresh(node)
    return NodeView(**node_view(node, settings))


@router.post("/nodes/{node_id}/online", response_model=NodeView)
async def post_node_online(
    node_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> NodeView:
    """Bring an offline node back online (eligible again when healthy/capable)."""
    node = await online_node(session, node_id)
    await session.commit()
    await session.refresh(node)
    return NodeView(**node_view(node, settings))


@router.delete("/nodes/{node_id}", response_model=NodeView)
async def delete_node(
    node_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> NodeView:
    """Soft-delete a node (keep the row; excluded from scheduling)."""
    node = await soft_delete_node(session, node_id)
    await session.commit()
    await session.refresh(node)
    return NodeView(**node_view(node, settings))
