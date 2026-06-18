"""Health endpoint. Always HTTP 200; ``database`` reflects DB reachability."""

from __future__ import annotations

from dopilot_protocol import HealthResponse
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ... import __version__
from ...db import engine as db_engine
from ...db.engine import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    """Return the frozen web ``{status, service, version, database}`` shape.

    Always HTTP 200. ``database`` is ``"ok"`` when ``SELECT 1`` succeeds, else
    ``"error"`` (and ``status`` becomes ``"degraded"``).
    """
    reachable = await db_engine.ping(session)
    payload = HealthResponse(
        status="ok" if reachable else "degraded",
        service="dopilot-server",
        version=__version__,
        database="ok" if reachable else "error",
    )
    # Web contract is the 4-field subset; richer protocol fields (agent_id,
    # capabilities, workdir) are agent-side only.
    return {
        "status": payload.status,
        "service": payload.service,
        "version": payload.version,
        "database": payload.database,
    }
