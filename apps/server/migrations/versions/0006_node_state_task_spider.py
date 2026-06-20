"""phase 1.7.1: node scheduling-state + soft delete, task spider column

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-20

Adds the Phase 1.7.1 backend support columns:

- ``nodes`` gains ``scheduling_enabled`` (bool, default true),
  ``scheduling_disabled_at`` and ``deleted_at`` (nullable timestamps). Offline
  is a reversible scheduling-control state; delete is a soft delete so
  historical references can still render a deleted node. Neither is touched by
  the heartbeat upsert.
- ``tasks`` gains an indexed ``spider`` column populated at task creation from
  the parsed Scrapy params, backing the execution-list spider filter. Existing
  rows are backfilled from ``params->>'spider'`` so pre-1.7.1 history stays
  filterable right after upgrade.

Uses PostgreSQL-compatible types; the SQLite test DB is built from the models
directly (tests/conftest.py), not this migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "scheduling_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "nodes",
        sa.Column(
            "scheduling_disabled_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "nodes",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("tasks", sa.Column("spider", sa.String(), nullable=True))
    # Backfill the new column from existing rows so pre-1.7.1 history is
    # spider-filterable immediately after upgrade. ``params`` is JSONB on
    # PostgreSQL, so ``->>'spider'`` extracts the value (NULL when absent).
    op.execute(
        "UPDATE tasks SET spider = params ->> 'spider' "
        "WHERE spider IS NULL AND params ->> 'spider' IS NOT NULL"
    )
    op.create_index("ix_tasks_spider", "tasks", ["spider"])


def downgrade() -> None:
    op.drop_index("ix_tasks_spider", table_name="tasks")
    op.drop_column("tasks", "spider")
    op.drop_column("nodes", "deleted_at")
    op.drop_column("nodes", "scheduling_disabled_at")
    op.drop_column("nodes", "scheduling_enabled")
