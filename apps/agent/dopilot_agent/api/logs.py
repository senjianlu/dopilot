"""Log tail + cleanup endpoints.

``GET /logs/tail`` does a real byte-offset read of the attempt's scrapyd
``job.log`` (see :func:`~dopilot_agent.logs.tail.tail_file`); ``finished`` is
the attempt's terminal status, resolved from scrapyd. ``POST
/executions/{attempt_id}/logs/cleanup`` deletes the job.log + state file and is
safe to call repeatedly. Both sit behind the shared-token guard.
"""

from __future__ import annotations

from pathlib import Path

from dopilot_protocol import AttemptStatus, CleanupResponse, LogStream, TailResponse
from fastapi import APIRouter, Depends, Query

from ..auth.dependencies import require_agent_token
from ..deps import get_scrapy_runner, get_state_store
from ..errors import not_found
from ..logs.tail import tail_file
from ..runners.scrapyd import ScrapyRunner
from ..state.store import StateStore

router = APIRouter()

_TERMINAL = {AttemptStatus.finished, AttemptStatus.failed, AttemptStatus.canceled}


@router.get("/logs/tail", response_model=TailResponse)
async def tail_logs(
    execution_id: str = Query(...),
    attempt_id: str = Query(...),
    stream: LogStream = Query(default=LogStream.log),
    offset: int = Query(default=0),
    max_bytes: int = Query(default=262144),
    runner: ScrapyRunner = Depends(get_scrapy_runner),
    store: StateStore = Depends(get_state_store),
    _: None = Depends(require_agent_token),
) -> TailResponse:
    state = store.read(attempt_id)
    if state is None:
        # No mapping at all => the attempt is unknown to this agent.
        raise not_found(
            "agent.attempt_not_found",
            "errors.notFound",
            {"attempt_id": attempt_id},
        )

    status = await runner.status(attempt_id, execution_id)
    finished = status.status in _TERMINAL

    result = tail_file(state.log_path, offset, max_bytes)
    return TailResponse(
        start_offset=result.start_offset,
        end_offset=result.end_offset,
        content=result.content,
        eof=result.eof,
        finished=finished,
    )


@router.post(
    "/executions/{attempt_id}/logs/cleanup", response_model=CleanupResponse
)
async def cleanup_logs(
    attempt_id: str,
    store: StateStore = Depends(get_state_store),
    _: None = Depends(require_agent_token),
) -> CleanupResponse:
    state = store.read(attempt_id)
    removed = False

    if state is not None:
        log_path = Path(state.log_path)
        try:
            log_path.unlink()
            removed = True
        except FileNotFoundError:
            pass

    if store.delete(attempt_id):
        removed = True

    return CleanupResponse(attempt_id=attempt_id, removed=removed)
