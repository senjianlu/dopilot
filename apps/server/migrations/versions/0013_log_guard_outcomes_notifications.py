"""log-flood guard: execution stats, task outcomes, schedule ledger, notifications

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-22

Task ``.ai/2026-08-22/log-flood-guard-and-notifications`` (decision 0021).

- ``executions``: terminal-only scrapy stats the agent parses from the log tail
  (``error_count`` / ``finish_reason``) and the final local ``log_bytes``.
- ``tasks``: ``schedule_generation`` (fixed at creation; backfilled to 0 for
  every existing schedule task so pre-upgrade tasks still count toward the
  schedule's current generation 0), plus the outcome-recorder stamp
  (``outcome_recorded_at`` / ``outcome_erroneous``) and its lookup index.
- ``execution_log_files``: ``truncation_reason`` (size-cap / dir-budget /
  maintenance).
- ``schedules``: derived ``consecutive_error_count``, ``auto_disabled_at`` /
  ``auto_disabled_reason`` and the re-enable ``outcome_generation``.
- NEW ``schedule_outcome_ledger``: per-schedule task outcomes independent of
  task retention (ON DELETE CASCADE with the schedule).
- NEW ``notifications`` with the partial unique index
  ``(type, dedupe_key) WHERE read_at IS NULL`` the upsert targets.

All additive; ``downgrade`` drops everything it added.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("executions", sa.Column("error_count", sa.Integer(), nullable=True))
    op.add_column("executions", sa.Column("finish_reason", sa.String(), nullable=True))
    op.add_column("executions", sa.Column("log_bytes", sa.BigInteger(), nullable=True))

    op.add_column("tasks", sa.Column("schedule_generation", sa.Integer(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("tasks", sa.Column("outcome_erroneous", sa.Boolean(), nullable=True))
    op.create_index(
        "ix_tasks_status_outcome_recorded_at",
        "tasks",
        ["status", "outcome_recorded_at"],
    )
    # Pre-upgrade schedule tasks belong to generation 0 (the schedules' initial
    # outcome_generation), so their outcomes are still counted after upgrade.
    op.execute("UPDATE tasks SET schedule_generation = 0 WHERE schedule_id IS NOT NULL")

    op.add_column(
        "execution_log_files", sa.Column("truncation_reason", sa.String(), nullable=True)
    )

    op.add_column(
        "schedules",
        sa.Column(
            "consecutive_error_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "schedules",
        sa.Column("auto_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("schedules", sa.Column("auto_disabled_reason", _JSON, nullable=True))
    op.add_column(
        "schedules",
        sa.Column("outcome_generation", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "schedule_outcome_ledger",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "schedule_id",
            sa.String(length=32),
            sa.ForeignKey("schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erroneous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_schedule_outcome_ledger_schedule_id",
        "schedule_outcome_ledger",
        ["schedule_id"],
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="warning"),
        sa.Column("payload", _JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_notifications_read_created", "notifications", ["read_at", "created_at"]
    )
    op.create_index(
        "uq_notifications_active_dedupe",
        "notifications",
        ["type", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("read_at IS NULL"),
        sqlite_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_notifications_active_dedupe", table_name="notifications")
    op.drop_index("ix_notifications_read_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(
        "ix_schedule_outcome_ledger_schedule_id", table_name="schedule_outcome_ledger"
    )
    op.drop_table("schedule_outcome_ledger")
    op.drop_column("schedules", "outcome_generation")
    op.drop_column("schedules", "auto_disabled_reason")
    op.drop_column("schedules", "auto_disabled_at")
    op.drop_column("schedules", "consecutive_error_count")
    op.drop_column("execution_log_files", "truncation_reason")
    op.drop_index("ix_tasks_status_outcome_recorded_at", table_name="tasks")
    op.drop_column("tasks", "outcome_erroneous")
    op.drop_column("tasks", "outcome_recorded_at")
    op.drop_column("tasks", "schedule_generation")
    op.drop_column("executions", "log_bytes")
    op.drop_column("executions", "finish_reason")
    op.drop_column("executions", "error_count")
