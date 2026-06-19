"""phase 1.5: command_outbox, event_audit, log integrity/gap, lost reconcile

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19

Redis Streams server<->agent communication (see
docs/refactor/00-redis-streams-agent-communication.md). Adds the command outbox,
the event dedupe/audit table, log-integrity + gap columns, and the
attempt reconcile/lost-reason columns. PostgreSQL types (JSONB) match the ORM
models; the SQLite test DB is built from the models, not this migration.

This is additive only — it does NOT touch the 0001/0002 schema beyond adding
columns. ``nodes.last_seen_at`` already exists (0001); only its write source
flips (server poll -> agent heartbeat), which needs no DDL.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- command outbox (server -> agent producer outbox) ------------------
    op.create_table(
        "command_outbox",
        sa.Column("command_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("intent", sa.String(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retry", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("redis_msg_id", sa.String(), nullable=True),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("give_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("command_id"),
    )
    op.create_index(
        "ix_command_outbox_execution_id", "command_outbox", ["execution_id"]
    )
    op.create_index(
        "ix_command_outbox_attempt_id", "command_outbox", ["attempt_id"]
    )

    # --- event audit / dedupe ---------------------------------------------
    op.create_table(
        "event_audit",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("redis_msg_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stream", "redis_msg_id", name="uq_event_audit_stream_msg"
        ),
    )
    op.create_index("ix_event_audit_attempt_id", "event_audit", ["attempt_id"])

    # --- execution_attempts: reconcile / lost-reason / stall clock ---------
    op.add_column(
        "execution_attempts",
        sa.Column("reconciled_from", sa.String(), nullable=True),
    )
    op.add_column(
        "execution_attempts",
        sa.Column("lost_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "execution_attempts",
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "execution_attempts",
        sa.Column("stalled_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- execution_log_files: integrity (decoupled from lifecycle) + gap ---
    op.add_column(
        "execution_log_files",
        sa.Column(
            "log_integrity",
            sa.String(),
            nullable=False,
            server_default="complete",
        ),
    )
    op.add_column(
        "execution_log_files",
        sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "execution_log_files",
        sa.Column("first_gap_expected_offset", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "execution_log_files",
        sa.Column("first_gap_actual_offset", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_log_files", "first_gap_actual_offset")
    op.drop_column("execution_log_files", "first_gap_expected_offset")
    op.drop_column("execution_log_files", "gap_count")
    op.drop_column("execution_log_files", "log_integrity")

    op.drop_column("execution_attempts", "stalled_at")
    op.drop_column("execution_attempts", "last_event_at")
    op.drop_column("execution_attempts", "lost_reason")
    op.drop_column("execution_attempts", "reconciled_from")

    op.drop_index("ix_event_audit_attempt_id", table_name="event_audit")
    op.drop_table("event_audit")

    op.drop_index("ix_command_outbox_attempt_id", table_name="command_outbox")
    op.drop_index("ix_command_outbox_execution_id", table_name="command_outbox")
    op.drop_table("command_outbox")
