"""phase 2.2: schedules.enabled timer gate

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-22

Phase 2.2 (see docs/phases/phase-2.2/00-brief.md). Adds the row-level
``schedules.enabled`` boolean that gates whether a schedule is registered with
APScheduler / fires on a timer. Server default is ``false`` so the column
backfills existing rows as disabled and matches the model default (new schedules
are created paused unless explicitly enabled). Distinct from the global
``[scheduler].enabled``.

PostgreSQL is the real schema authority; the SQLite test DB is built from the
models directly (tests/conftest.py), where the mapped column's ``default=False``
provides the same posture.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("schedules", "enabled")
