"""phase task-artifact-archive: build_artifacts.archived_at

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-24

Phase task-artifact-archive (see docs/phases/task-artifact-archive/00-brief.md).
Adds the nullable ``build_artifacts.archived_at`` timestamp that marks a build
artifact as archived. NULL = not archived; the API derives
``archived = archived_at is not None``. No broad status enum is introduced — the
archive state is exactly this nullable aware-UTC timestamp. Existing rows
backfill to NULL (not archived), which matches the model default.

PostgreSQL is the real schema authority; the SQLite test DB is built from the
models directly (tests/conftest.py), where the mapped column's nullability
provides the same posture.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "build_artifacts",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("build_artifacts", "archived_at")
