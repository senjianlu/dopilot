"""Run + stop endpoints.

``POST /run`` launches a Scrapy job via local scrapyd and persists the attempt
state file; ``POST /stop`` cancels an attempt idempotently. Both sit behind the
shared-token guard. The actual orchestration lives in
:class:`~dopilot_agent.runners.scrapyd.ScrapyRunner`; these handlers translate a
:class:`~dopilot_agent.runners.scrapyd.RunnerError` into the frozen error
envelope.
"""

from __future__ import annotations

from dopilot_protocol import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStopRequest,
    AgentStopResponse,
)
from fastapi import APIRouter, Depends

from ..auth.dependencies import require_agent_token
from ..deps import get_scrapy_runner
from ..errors import upstream_error
from ..runners.scrapyd import RunnerError, ScrapyRunner

router = APIRouter()


@router.post("/run", response_model=AgentRunResponse)
async def run(
    body: AgentRunRequest,
    runner: ScrapyRunner = Depends(get_scrapy_runner),
    _: None = Depends(require_agent_token),
) -> AgentRunResponse:
    try:
        return await runner.run(body)
    except RunnerError as exc:
        raise upstream_error(
            "agent.schedule_failed", "errors.upstream", exc.detail
        ) from exc


@router.post("/stop", response_model=AgentStopResponse)
async def stop(
    body: AgentStopRequest,
    runner: ScrapyRunner = Depends(get_scrapy_runner),
    _: None = Depends(require_agent_token),
) -> AgentStopResponse:
    # Idempotent by design: stopping a gone/unknown attempt returns
    # stopped=False with a resolved status, never an error.
    return await runner.stop(body.attempt_id, body.execution_id)
