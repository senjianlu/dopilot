"""Agent status endpoint (phase-1+ stub).

Will report live executor/runner state once runners exist. For now it returns
a 501 envelope behind the shared-token guard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.dependencies import require_agent_token
from ..errors import not_implemented

router = APIRouter()


@router.get("/status")
def status(_: None = Depends(require_agent_token)) -> None:
    raise not_implemented("status.not_implemented", "errors.notImplemented", {"phase": 1})
