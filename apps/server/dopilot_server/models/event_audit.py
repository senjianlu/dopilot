"""Event-audit / dedupe model (phase 1.5).

Records the outcome of every consumed agent status event so the server can (a)
dedupe replays by ``(stream, redis_msg_id)`` and (b) keep an audit trail of
terminal / lost-override decisions. PostgreSQL stays the authority for which
terminal events were applied.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

# Outcomes recorded per consumed event.
OUTCOME_APPLIED = "applied"
OUTCOME_SKIPPED_DUP = "skipped_dup"
OUTCOME_SKIPPED_TERMINAL = "skipped_terminal"
OUTCOME_OVERRIDE_LOST = "override_lost"
# cleanup-reconcile: agent reported alive on a server-lost attempt -> reclaim sent.
OUTCOME_RECLAIM_REQUESTED = "reclaim_requested"


def _new_id() -> str:
    return uuid.uuid4().hex


class EventAudit(Base):
    """One processed-event record (dedupe key + audit outcome)."""

    __tablename__ = "event_audit"
    __table_args__ = (
        UniqueConstraint("stream", "redis_msg_id", name="uq_event_audit_stream_msg"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    stream: Mapped[str] = mapped_column(String, nullable=False)
    redis_msg_id: Mapped[str] = mapped_column(String, nullable=False)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    # applied | skipped_dup | skipped_terminal | override_lost
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
