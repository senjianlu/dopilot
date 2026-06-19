"""Command outbox model (phase 1.5).

The transactional producer-outbox for server -> agent commands. A row is created
in the SAME PostgreSQL transaction as its ``execution`` / ``execution_attempt``;
the command dispatcher later XADDs it to the agent command stream and marks it
``sent``. This is a PG-internal outbox — never a cross-resource pseudo-
transaction; ``XADD`` always happens AFTER the business+outbox commit.

``command_id`` is the outbox row id / audit key; it is NOT the agent execution
idempotency key — that is always ``attempt_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")

# Outbox lifecycle. ``dispatching`` is the transient state where a delivery path
# has taken the row and is mid-XADD (counted as "un-terminated" for coalesce).
OUTBOX_PENDING = "pending"
OUTBOX_DISPATCHING = "dispatching"
OUTBOX_SENT = "sent"
OUTBOX_FAILED_RETRYABLE = "failed_retryable"
OUTBOX_FAILED = "failed"
OUTBOX_CANCELED = "canceled"

#: Outbox rows that are not yet terminally resolved (for coalesce / cancel CAS).
OUTBOX_UNRESOLVED = frozenset(
    {OUTBOX_PENDING, OUTBOX_DISPATCHING, OUTBOX_FAILED_RETRYABLE}
)
#: Rows a periodic dispatcher should attempt to (re)deliver.
OUTBOX_DISPATCHABLE = frozenset({OUTBOX_PENDING, OUTBOX_FAILED_RETRYABLE})


def _new_id() -> str:
    return uuid.uuid4().hex


class CommandOutbox(Base):
    """One pending/sent server -> agent command (run / stop / cleanup_logs)."""

    __tablename__ = "command_outbox"

    command_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=_new_id
    )
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    execution_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # run | stop | cleanup_logs
    type: Mapped[str] = mapped_column(String, nullable=False)
    # cancel | reclaim (only for stop)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    # pending | dispatching | sent | failed_retryable | failed | canceled
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=OUTBOX_PENDING
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retry: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Redis stream message id once XADDed — audit/reconcile only, NOT a resend key.
    redis_msg_id: Mapped[str | None] = mapped_column(String, nullable=True)
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    give_up_at: Mapped[datetime | None] = mapped_column(
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
