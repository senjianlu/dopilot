"""Node model: a registered/discovered agent worker endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Node(Base):
    """An agent endpoint and its last-known health/capabilities snapshot.

    ``capabilities`` uses JSONB on PostgreSQL and falls back to JSON on other
    dialects (e.g. SQLite in tests).
    """

    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True
    )
    endpoint: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    capabilities: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
