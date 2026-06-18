"""Agent health endpoint.

GET /health is intentionally UNAUTHENTICATED so container healthchecks and the
server's node-probe can reach it without a token.

It returns the frozen ``HealthResponse`` fields (status/service/version/
agent_id/capabilities/workdir) AND merges a non-protocol ``detail`` key carrying
the local scrapyd subprocess health::

    {"scrapyd": {"running": bool, "port": int, "pid": int | None}}

The protocol ``HealthResponse`` has no ``detail`` field and must not be changed,
so the handler builds the model's dict and returns a ``JSONResponse`` with the
extra key merged in.
"""

from __future__ import annotations

from dopilot_protocol import CapabilitySet, HealthResponse
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import __version__
from ..config.loader import get_settings
from ..config.settings import Settings
from ..deps import get_scrapyd_process
from ..scrapyd.process import ScrapydProcess

router = APIRouter()


@router.get("/health")
def health(
    settings: Settings = Depends(get_settings),
    process: ScrapydProcess | None = Depends(get_scrapyd_process),
) -> JSONResponse:
    base = HealthResponse(
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

    if process is not None:
        scrapyd_detail = {
            "running": process.is_running(),
            "port": process.port,
            "pid": process.pid,
        }
    else:
        # No managed subprocess (e.g. [scrapyd].start = false): report from cfg.
        scrapyd_detail = {
            "running": False,
            "port": settings.scrapyd.port,
            "pid": None,
        }

    payload = base.model_dump()
    payload["detail"] = {"scrapyd": scrapyd_detail}
    return JSONResponse(content=payload)
