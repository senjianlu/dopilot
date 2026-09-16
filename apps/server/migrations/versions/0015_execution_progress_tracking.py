"""execution progress tracking (no-progress stall detection)

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable with no backfill: an execution that predates this migration
    # simply has no progress history, and the detector requires a fresh sample
    # before it will judge anything, so old rows are skipped rather than
    # mis-flagged.
    op.add_column(
        "executions",
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column(
            "last_progress_sample_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "executions",
        sa.Column("no_progress_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("executions", "no_progress_at")
    op.drop_column("executions", "last_progress_sample_at")
    op.drop_column("executions", "last_progress_at")
