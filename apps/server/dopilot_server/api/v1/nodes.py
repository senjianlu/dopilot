"""Node endpoints: list known nodes.

Phase 1.5: node liveness/health is sourced from agent heartbeats
(``POST /api/v1/agents/{agent_id}/heartbeat``), not a server-driven ``/health``
poll, so the old ``POST /nodes/refresh`` is gone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...nodes.service import list_nodes
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
