"""Auth endpoints: single-admin login + identity introspection."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...auth.tokens import issue_token
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...errors import ApiError
from .schemas import LoginRequest, LoginResponse, MeResponse

router = APIRouter(tags=["auth"])


def _constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    """Authenticate the single admin and (when auth is ON) mint a token."""
    if not settings.auth.enabled:
        return LoginResponse(
            mode="off",
            access_token=None,
            token_type="bearer",
            expires_at=None,
        )

    user_ok = _constant_time_equals(body.username, settings.auth.admin_username or "")
    pass_ok = _constant_time_equals(body.password, settings.auth.admin_password or "")
    if not (user_ok and pass_ok):
        raise ApiError(
            401,
            "auth.invalid_credentials",
            "errors.invalidCredentials",
            {},
        )

    token, expires_at = await issue_token(session, settings)
    return LoginResponse(
        mode="on",
        access_token=token,
        token_type="bearer",
        expires_at=expires_at.isoformat(),
    )


@router.get("/auth/me", response_model=MeResponse)
async def me(
    admin: AdminContext = Depends(get_current_admin),
) -> MeResponse:
    """Return the current identity (anonymous admin when auth is OFF)."""
    return MeResponse(
        authenticated=admin.authenticated,
        mode=admin.mode,
        username=admin.username,
        expires_at=admin.expires_at.isoformat() if admin.expires_at else None,
    )
