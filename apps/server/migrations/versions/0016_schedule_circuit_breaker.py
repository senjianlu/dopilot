"""schedule circuit breaker (decision 0025)

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # Every existing schedule starts ``closed`` (server defaults backfill the two
    # NOT NULL columns). Rows auto-disabled under 0021 keep ``enabled=false`` and
    # their ``auto_disabled_*`` untouched — the user re-enables them by hand.
    op.add_column(
        "schedules",
        sa.Column("breaker_state", sa.String(), nullable=False, server_default="closed"),
    )
    op.add_column(
        "schedules",
        sa.Column("breaker_level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "schedules",
        sa.Column("breaker_opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "schedules",
        sa.Column("breaker_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "schedules",
        sa.Column("breaker_escalated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("schedules", sa.Column("breaker_reason", _JSON, nullable=True))
    op.add_column(
        "schedules", sa.Column("breaker_artifact_id", sa.String(length=32), nullable=True)
    )
    # Pre-0016 ledger rows stay NULL; an erroneous NULL is read as ``broken``.
    op.add_column(
        "schedule_outcome_ledger", sa.Column("outcome_class", sa.String(), nullable=True)
    )
    op.add_column(
        "executions", sa.Column("outcome_class", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("executions", "outcome_class")
    op.drop_column("schedule_outcome_ledger", "outcome_class")
    op.drop_column("schedules", "breaker_artifact_id")
    op.drop_column("schedules", "breaker_reason")
    op.drop_column("schedules", "breaker_escalated_at")
    op.drop_column("schedules", "breaker_retry_at")
    op.drop_column("schedules", "breaker_opened_at")
    op.drop_column("schedules", "breaker_level")
    op.drop_column("schedules", "breaker_state")
