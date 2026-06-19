"""Agent heartbeat endpoint (phase 1.5).

``POST /api/v1/agents/{agent_id}/heartbeat`` — the agent-initiated liveness +
capability report that REPLACES server polling of agent ``/health``. Authn uses
the dedicated agent -> server token (``require_server_token``), not the web admin
token. Health is judged as ``now - nodes.last_seen_at <= heartbeat_timeout``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import AgentHeartbeatRequest, AgentHeartbeatResponse
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.agent_dependencies import require_server_token
from ...db.engine import get_session
from ...errors import ApiError
from ...nodes.service import upsert_node_heartbeat

router = APIRouter(tags=["agents"])


@router.post(
    "/agents/{agent_id}/heartbeat",
    response_model=AgentHeartbeatResponse,
    dependencies=[Depends(require_server_token)],
)
async def post_heartbeat(
    agent_id: str,
    body: AgentHeartbeatRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentHeartbeatResponse:
    """Record an agent heartbeat (upsert node liveness + capabilities)."""
    if body.agent_id != agent_id:
        raise ApiError(
            400,
            "agent.heartbeat_id_mismatch",
            "errors.heartbeatIdMismatch",
            {"path_agent_id": agent_id, "body_agent_id": body.agent_id},
        )
    await upsert_node_heartbeat(session, agent_id, body)
    await session.commit()
    return AgentHeartbeatResponse(server_time=datetime.now(UTC).isoformat())
