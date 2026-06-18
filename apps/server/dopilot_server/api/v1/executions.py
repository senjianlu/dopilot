"""Execution endpoints (phase-0 stubs returning the 501 envelope)."""

from __future__ import annotations

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse
from fastapi import APIRouter, Depends

from ...auth.dependencies import AdminContext, get_current_admin
from ...errors import ApiError
from ...executors.registry import get_executor

router = APIRouter(tags=["executions"])


@router.post("/executions/run", response_model=ExecutionRunResponse)
async def run_execution(
    body: ExecutionRunRequest,
    _admin: AdminContext = Depends(get_current_admin),
) -> ExecutionRunResponse:
    """Resolve the executor and dispatch.

    Phase 0: the only registered executor (scrapy) raises a 501 envelope.
    """
    executor = get_executor(body.task_type)
    return await executor.run(body)


@router.get("/executions/{execution_id}/logs/stream")
async def stream_logs(
    execution_id: str,
    _admin: AdminContext = Depends(get_current_admin),
):
    """Realtime log stream (server->web SSE). Implemented in phase 1."""
    raise ApiError(
        501,
        "logs.stream_not_implemented",
        "errors.notImplemented",
        {"phase": 1},
    )
