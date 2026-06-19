"""phase 1.7: rename execution-domain to task/execution; add no_target reason

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19

Phase 1.7 packet 1 (see docs/phases/phase-1.7/00-brief.md). Inverts the
parent/atomic vocabulary so the server domain reads as task -> execution:

- table ``executions`` (parent logical run)  -> ``tasks``
- table ``execution_attempts`` (atomic unit) -> ``executions``
- atomic FK column ``execution_id`` -> ``task_id`` (now references ``tasks.id``)
- add ``tasks.status_reason`` + ``tasks.status_detail`` for the terminal
  ``no_target`` task (no healthy node -> zero executions).

⚠️ SEAM PRESERVED. The Redis/disk/agent wire is untouched: the columns
``execution_id`` / ``attempt_id`` on ``command_outbox``, ``event_audit`` and
``execution_log_files`` are NOT renamed — there ``execution_id`` still means the
parent (task) id and ``attempt_id`` the atomic (execution) id, matching the
agent payloads and the on-disk ``{execution_id}/{attempt_id}.log`` path.

This rename uses ``rename_table`` / ``alter_column`` and is therefore
data-preserving. (dopilot is greenfield/single-admin with no production data, so
preservation is not required, but the rename costs nothing to keep.) The SQLite
test DB is built from the models directly (tests/conftest.py), not this
migration; PostgreSQL is the real schema authority.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # parent run: executions -> tasks
    op.rename_table("executions", "tasks")
    # atomic unit: execution_attempts -> executions
    op.rename_table("execution_attempts", "executions")
    # atomic FK column -> task_id (its FK now resolves to the renamed tasks.id)
    op.execute("ALTER TABLE executions RENAME COLUMN execution_id TO task_id")
    # keep the FK index name in step with the new table/column
    op.drop_index(
        "ix_execution_attempts_execution_id", table_name="executions"
    )
    op.create_index("ix_executions_task_id", "executions", ["task_id"])

    # task-level reason for a non-business terminal (currently no_target).
    op.add_column(
        "tasks",
        sa.Column("status_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "status_detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "status_detail")
    op.drop_column("tasks", "status_reason")

    op.drop_index("ix_executions_task_id", table_name="executions")
    op.create_index(
        "ix_execution_attempts_execution_id", "executions", ["task_id"]
    )
    op.execute("ALTER TABLE executions RENAME COLUMN task_id TO execution_id")
    op.rename_table("executions", "execution_attempts")
    op.rename_table("tasks", "executions")
