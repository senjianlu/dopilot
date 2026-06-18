"""Opaque-token issuance and verification.

The plaintext token is an unguessable ``secrets.token_urlsafe`` value handed to
the client. Only its HMAC-SHA256 hex hash (keyed by ``token_secret``) is
persisted, so a DB leak does not expose usable tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..models.auth_token import AuthToken


def hash_token(secret: str, token: str) -> str:
    """Return the HMAC-SHA256 hex digest of ``token`` keyed by ``secret``."""
    return hmac.new(
        secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def issue_token(
    session: AsyncSession, settings: Settings
) -> tuple[str, datetime]:
    """Mint a new opaque token, persist its hash, and return (token, expires_at).

    The expiry is ``now + access_token_ttl_minutes`` (timezone-aware UTC).
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.auth.access_token_ttl_minutes
    )
    row = AuthToken(
        token_hash=hash_token(settings.auth.token_secret or "", token),
        expires_at=expires_at,
        revoked=False,
    )
    session.add(row)
    await session.commit()
    return token, expires_at


def _aware_utc(value: datetime) -> datetime:
    """Normalize a possibly-naive datetime to aware UTC (SQLite returns naive)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def get_token_record(
    session: AsyncSession, settings: Settings, token: str
) -> AuthToken | None:
    """Return the live (non-revoked, unexpired) ``AuthToken`` row, or None."""
    if not token:
        return None
    token_hash = hash_token(settings.auth.token_secret or "", token)
    result = await session.execute(
        select(AuthToken).where(AuthToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None or row.revoked:
        return None
    if _aware_utc(row.expires_at) <= datetime.now(UTC):
        return None
    return row


async def verify_token(
    session: AsyncSession, settings: Settings, token: str
) -> bool:
    """Return True iff ``token`` maps to a live (non-revoked, unexpired) row."""
    return await get_token_record(session, settings, token) is not None
