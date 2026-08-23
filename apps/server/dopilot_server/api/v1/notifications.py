"""Notification center endpoints (log-flood guard / auto-disable).

Admin-only. The web bell polls ``unread-count`` and fetches the list when the
dropdown opens; rendering is i18n by ``type`` + ``payload`` on the client.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...db.engine import get_session
from ...errors import ApiError
from ...services import notifications as svc
from .schemas import (
    NotificationsReadRequest,
    NotificationsReadResponse,
    NotificationsResponse,
    NotificationUnreadCountResponse,
    NotificationView,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationsResponse)
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=200),
    before: str | None = Query(default=None),
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationsResponse:
    cutoff: datetime | None = None
    if before:
        try:
            cutoff = datetime.fromisoformat(before)
        except ValueError as exc:
            raise ApiError(
                400, "notifications.invalid_before", "errors.invalidCutoff", {"before": before}
            ) from exc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
    rows = await svc.list_notifications(
        session, unread_only=unread_only, limit=limit, before=cutoff
    )
    unread = await svc.unread_count(session)
    return NotificationsResponse(
        notifications=[NotificationView(**svc.notification_view(r)) for r in rows],
        unread_count=unread,
    )


@router.get("/notifications/unread-count", response_model=NotificationUnreadCountResponse)
async def unread_count(
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationUnreadCountResponse:
    return NotificationUnreadCountResponse(unread_count=await svc.unread_count(session))


@router.post("/notifications/read", response_model=NotificationsReadResponse)
async def mark_read(
    body: NotificationsReadRequest,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationsReadResponse:
    marked = await svc.mark_read(session, body.ids)
    await session.commit()
    return NotificationsReadResponse(marked=marked)


@router.post("/notifications/read-all", response_model=NotificationsReadResponse)
async def mark_all_read(
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationsReadResponse:
    marked = await svc.mark_all_read(session)
    await session.commit()
    return NotificationsReadResponse(marked=marked)
