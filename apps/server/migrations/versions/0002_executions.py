"""phase 1: executions, attempts, log-file index, scrapy artifacts; nodes.health

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-18

Uses PostgreSQL types (JSONB) to match the ORM models. dopilot's only database
is PostgreSQL; the SQLite test DB is built from the models directly (see
tests/conftest.py), not from this migration. Upgrades a phase-0 schema (0001:
nodes, auth_tokens) to the phase-1 Scrapy schema.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # nodes: add agent health detail (e.g. scrapyd subprocess status).
    op.add_column(
        "nodes",
        sa.Column(
            "health",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "executions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "node_strategy", sa.String(), nullable=False, server_default="all"
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="queued"
        ),
        sa.Column(
            "params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "execution_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.Column("remote_job_id", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column(
            "error_detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_execution_attempts_execution_id",
        "execution_attempts",
        ["execution_id"],
    )

    op.create_table(
        "execution_log_files",
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("stream", sa.String(), nullable=False, server_default="log"),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column(
            "size_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "last_pulled_offset",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("final_offset", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="active"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retained_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("execution_id", "attempt_id", "stream"),
    )

    op.create_table(
        "scrapy_artifacts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column(
            "size_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("scrapy_artifacts")
    op.drop_table("execution_log_files")
    op.drop_index(
        "ix_execution_attempts_execution_id", table_name="execution_attempts"
    )
    op.drop_table("execution_attempts")
    op.drop_table("executions")
    op.drop_column("nodes", "health")
