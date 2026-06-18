"""Agent health endpoint.

GET /health is intentionally UNAUTHENTICATED so container healthchecks and the
server's node-probe can reach it without a token.
"""

from __future__ import annotations

from dopilot_protocol import CapabilitySet, HealthResponse
from fastapi import APIRouter, Depends

from .. import __version__
from ..config.loader import get_settings
from ..config.settings import Settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="dopilot-agent",
        version=__version__,
        agent_id=settings.agent.agent_id,
        capabilities=CapabilitySet(
            scrapy=settings.capabilities.scrapy,
            script=settings.capabilities.script,
            docker=settings.capabilities.docker,
        ),
        workdir=settings.agent.workdir,
    )
