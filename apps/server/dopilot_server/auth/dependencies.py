"""The ``get_current_admin`` FastAPI dependency (single-admin auth).

Web admin auth is **fail-closed** (phase 2.2): a valid Bearer token is required
unless auth is explicitly disabled via ``DOPILOT_AUTH_DISABLED=true``, in which
case the platform runs as an anonymous admin and protected endpoints are open.
(This is distinct from agent/server machine auth, which stays
"config-present-or-off".)
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.loader import get_settings
from ..config.settings import Settings
from ..db.engine import get_session
from ..errors import ApiError
from .tokens import get_token_record


@dataclass
class AdminContext:
    """Resolved identity for the current request."""

    mode: str  # "on" | "off"
    username: str | None
    authenticated: bool
    expires_at: datetime | None


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


async def get_current_admin(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> AdminContext:
    """Resolve the admin identity, or raise 401 when auth is ON and invalid."""
    if not settings.auth.enabled:
        return AdminContext(
            mode="off",
            username="admin",
            authenticated=True,
            expires_at=None,
        )

    token = _extract_bearer(request)

    # Static admin API token (phase 2.2.2): a non-empty configured
    # ``admin_api_token`` matching the Bearer token authenticates as admin with
    # no expiry. Both sides must be non-empty (``hmac.compare_digest("", "")`` is
    # True, so an empty configured token must NOT match an empty/missing bearer),
    # and the compare is constant-time. This stays inside the ``auth.enabled``
    # branch, so it never bypasses fail-closed auth.
    api_token = (settings.auth.admin_api_token or "").strip()
    if api_token and token and hmac.compare_digest(token, api_token):
        return AdminContext(
            mode="on",
            username=settings.auth.admin_username,
            authenticated=True,
            expires_at=None,
        )

    record = await get_token_record(session, settings, token) if token else None
    if record is None:
        raise ApiError(401, "auth.unauthorized", "errors.unauthorized", {})

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    return AdminContext(
        mode="on",
        username=settings.auth.admin_username,
        authenticated=True,
        expires_at=expires_at,
    )
