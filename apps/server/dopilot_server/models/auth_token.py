"""AuthToken model: server-issued opaque admin tokens (stored hashed only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class AuthToken(Base):
    """A single issued bearer token, persisted as an HMAC-SHA256 hex hash.

    The plaintext token is NEVER stored; only ``token_hash`` is. Validation
    recomputes the hash and checks ``revoked`` and ``expires_at``.
    """

    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
