"""Manual maintenance endpoints (phase 1.8.2).

Operator-driven, manual-only. There is NO scheduled cleanup in phase 1.8.2.
Standard admin auth is enough (no extra RBAC layer).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...errors import ApiError
from ...services import maintenance as svc
from .schemas import TerminalCleanupRequest, TerminalCleanupResponse

router = APIRouter(tags=["maintenance"])


def _resolve_cutoff(body: TerminalCleanupRequest) -> datetime:
    """Resolve the request to an aware cutoff datetime.

    ``before`` (absolute ISO) wins when given; otherwise ``older_than_days`` is
    subtracted from now. Exactly one must be provided.
    """
    if body.before:
        try:
            cutoff = datetime.fromisoformat(body.before)
        except ValueError as exc:
            raise ApiError(
                400,
                "maintenance.invalid_cutoff",
                "errors.invalidCutoff",
                {"before": body.before},
            ) from exc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        return cutoff
    if body.older_than_days is not None:
        return datetime.now(UTC) - timedelta(days=body.older_than_days)
    raise ApiError(
        400,
        "maintenance.cutoff_required",
        "errors.cutoffRequired",
        {},
    )


@router.post(
    "/maintenance/terminal-cleanup", response_model=TerminalCleanupResponse
)
async def terminal_cleanup(
    body: TerminalCleanupRequest,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> TerminalCleanupResponse:
    """Delete (or dry-run preview) old TERMINAL task data before a cutoff.

    Only terminal tasks (complete/failed/canceled/lost/no_target) older than the
    cutoff are affected; queued/running/finalizing tasks are never touched.
    """
    cutoff = _resolve_cutoff(body)
    summary = await svc.cleanup_terminal_data(
        session, settings, cutoff=cutoff, dry_run=body.dry_run
    )
    if not body.dry_run:
        await session.commit()
    return TerminalCleanupResponse(**summary.as_dict())
