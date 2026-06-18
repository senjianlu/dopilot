"""Log tail + cleanup endpoints (phase-1+ stubs).

The query schema for ``GET /logs/tail`` mirrors the frozen ``TailRequest``
contract so the wire shape is fixed now even though the handler returns a 501
envelope. The real tail provider (a ``LogSource``-backed reader over files
under the agent workdir) lands in phase 1.
"""

from __future__ import annotations

from dopilot_protocol import LogStream
from fastapi import APIRouter, Depends, Query

from ..auth.dependencies import require_agent_token
from ..errors import not_implemented

router = APIRouter()


@router.get("/logs/tail")
def tail_logs(
    execution_id: str = Query(...),
    attempt_id: str = Query(...),
    stream: LogStream = Query(default=LogStream.log),
    offset: int = Query(default=0),
    max_bytes: int = Query(default=262144),
    _: None = Depends(require_agent_token),
) -> None:
    raise not_implemented(
        "logs.tail_not_implemented", "errors.notImplemented", {"phase": 1}
    )


@router.post("/executions/{attempt_id}/logs/cleanup")
def cleanup_logs(
    attempt_id: str,
    _: None = Depends(require_agent_token),
) -> None:
    raise not_implemented(
        "logs.cleanup_not_implemented", "errors.notImplemented", {"phase": 1}
    )
