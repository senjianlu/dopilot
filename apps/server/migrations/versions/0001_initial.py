"""initial schema: nodes, auth_tokens

Revision ID: 0001
Revises:
Create Date: 2026-06-18

Uses PostgreSQL types (UUID, JSONB) to match the ORM models. dopilot's only
database is PostgreSQL; the SQLite test DB is built from the models directly
(see tests/conftest.py), not from this migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("agent_id"),
        sa.UniqueConstraint("endpoint"),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:
    op.drop_table("auth_tokens")
    op.drop_table("nodes")
