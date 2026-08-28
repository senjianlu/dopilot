"""schedule concurrency gate: schedules.max_concurrency + tasks lookup index

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-28

Task ``.ai/2026-08-28/log-copy-and-schedule-concurrency`` (decision 0022).

- ``schedules.max_concurrency``: how many of a schedule's tasks may be ACTIVE at
  once. ``server_default="1"`` so EXISTING rows are backfilled to 1 — the
  deliberate behaviour change decision 0022 records (a schedule that used to
  overlap runs now serialises them). ``0`` means unlimited and is the escape
  hatch for anyone who relied on the old behaviour.
- ``ix_tasks_schedule_id_status``: the gate counts ACTIVE tasks per schedule on
  every firing, and ``tasks.schedule_id`` had no index at all before this.

Both additive; ``downgrade`` drops exactly what it added.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column(
            "max_concurrency",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index(
        "ix_tasks_schedule_id_status",
        "tasks",
        ["schedule_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_schedule_id_status", table_name="tasks")
    op.drop_column("schedules", "max_concurrency")
