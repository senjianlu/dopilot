"""Notification center rows (log-flood guard / auto-disable).

One row per operator-facing alert. ``type`` + ``payload`` are structured (the
web client renders the human text via i18n); the server never stores natural
language. Active (unread) rows are de-duplicated per ``(type, dedupe_key)`` by a
PARTIAL UNIQUE INDEX (``WHERE read_at IS NULL``) so concurrent writers from the
event/log consumers, the stream guard and the retention sweep collapse into one
row with an incrementing ``count`` (atomic upsert in ``services.notifications``).
Once read, the same key may produce a fresh row.

Bounded (decision 0019): the retention sweep prunes read rows past
``notification_retention_days``, unread rows past
``notification_unread_max_days``, and caps the table at
``notification_max_rows``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITY_RANK = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_ERROR: 2}

# Notification types (web renders each via i18n keys ``notifications.<type>``).
TYPE_SCHEDULE_AUTO_DISABLED = "schedule_auto_disabled"
TYPE_LOG_TRUNCATED = "log_truncated"
TYPE_LOG_FLOOD = "log_flood"
TYPE_REDIS_STREAM_OVER_BUDGET = "redis_stream_over_budget"
TYPE_LOGS_DIR_OVER_BUDGET = "logs_dir_over_budget"
TYPE_STALE_COMMAND_STREAMS_DELETED = "stale_command_streams_deleted"
TYPE_SENT_COMMANDS_REQUEUED = "sent_commands_requeued"


def _new_id() -> str:
    return uuid.uuid4().hex


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    type: Mapped[str] = mapped_column(String, nullable=False)
    # info | warning | error — only ever raised by an upsert, never lowered.
    severity: Mapped[str] = mapped_column(String, nullable=False, default=SEVERITY_WARNING)
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    read_at: Mapped[datetime | None] = mapped_column(
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
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_notifications_read_created", "read_at", "created_at"),
        # Active-period uniqueness: one UNREAD row per (type, dedupe_key). Both
        # PostgreSQL and SQLite support partial unique indexes; the service's
        # ON CONFLICT upsert targets exactly this index.
        Index(
            "uq_notifications_active_dedupe",
            "type",
            "dedupe_key",
            unique=True,
            postgresql_where=text("read_at IS NULL"),
            sqlite_where=text("read_at IS NULL"),
        ),
    )
