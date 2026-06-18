"""Node endpoints: list known/configured nodes and refresh their health."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...nodes.service import list_nodes, refresh_nodes
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


@router.post("/nodes/refresh", response_model=NodesResponse)
async def post_nodes_refresh(
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> NodesResponse:
    """Poll all configured agents, upsert health, and return the node list."""
    await refresh_nodes(session, settings)
    nodes = await list_nodes(session, settings)
    return NodesResponse(nodes=[NodeView(**n) for n in nodes])
