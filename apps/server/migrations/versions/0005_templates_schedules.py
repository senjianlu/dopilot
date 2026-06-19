"""phase 1.7 packet 2: task templates, schedules, task origin + snapshot

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19

Adds the scheduling domain above :class:`Task` (see
docs/phases/phase-1.7/00-brief.md and the packet-2 prompt):

- ``task_templates`` — reusable Scrapy run definitions.
- ``schedules`` — timers (interval / cron) that reference one template.
- ``tasks`` gains provenance + the immutable template snapshot:
  ``source`` (manual | schedule_trigger_now | schedule_timer), nullable
  ``template_id`` / ``schedule_id``, and ``template_snapshot`` (JSONB).

Uses PostgreSQL types (JSONB) to match the ORM models; the SQLite test DB is
built from the models directly (tests/conftest.py), not this migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_templates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "task_type", sa.String(), nullable=False, server_default="scrapy"
        ),
        sa.Column("project", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("spider", sa.String(), nullable=True),
        sa.Column(
            "artifact",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "args",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "node_strategy", sa.String(), nullable=False, server_default="all"
        ),
        sa.Column(
            "node_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("template_id", sa.String(length=32), nullable=False),
        sa.Column(
            "trigger_type",
            sa.String(),
            nullable=False,
            server_default="interval",
        ),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["template_id"], ["task_templates.id"]),
    )
    op.create_index(
        "ix_schedules_template_id", "schedules", ["template_id"]
    )

    # tasks: provenance + immutable template snapshot.
    op.add_column(
        "tasks",
        sa.Column(
            "source", sa.String(), nullable=False, server_default="manual"
        ),
    )
    op.add_column(
        "tasks", sa.Column("template_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("schedule_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column(
            "template_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "template_snapshot")
    op.drop_column("tasks", "schedule_id")
    op.drop_column("tasks", "template_id")
    op.drop_column("tasks", "source")
    op.drop_index("ix_schedules_template_id", table_name="schedules")
    op.drop_table("schedules")
    op.drop_table("task_templates")
