"""Agent status endpoint.

``GET /status?execution_id&attempt_id`` resolves the attempt's current state
from its state file + local scrapyd (see
:meth:`~dopilot_agent.runners.scrapyd.ScrapyRunner.status`). A missing state
mapping returns ``status=unknown`` with HTTP 200 (not 404) so the server can
mark the attempt lost rather than retry forever.
"""

from __future__ import annotations

from dopilot_protocol import AgentStatusResponse
from fastapi import APIRouter, Depends, Query

from ..auth.dependencies import require_agent_token
from ..deps import get_scrapy_runner
from ..runners.scrapyd import ScrapyRunner

router = APIRouter()


@router.get("/status", response_model=AgentStatusResponse)
async def status(
    execution_id: str = Query(...),
    attempt_id: str = Query(...),
    runner: ScrapyRunner = Depends(get_scrapy_runner),
    _: None = Depends(require_agent_token),
) -> AgentStatusResponse:
    return await runner.status(attempt_id, execution_id)
