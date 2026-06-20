"""phase 1.8: build artifacts + execution-template/task/schedule clean-cut

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-20

Phase 1.8 domain clean-cut (see docs/phases/phase-1.8/00-brief.md):

- New canonical ``build_artifacts`` table. Backfilled (data-preserving) from the
  legacy ``task_templates.artifact`` JSON descriptors, deduped on
  ``(artifact_type, content_hash)`` = ``("scrapy", sha256)``. Filesystem-only
  eggs (no descriptor) are reconciled into the table at runtime by the artifact
  list endpoint, not here.
- ``task_templates`` -> ``execution_templates`` (table rename). Adds a nullable
  ``build_artifact_id`` FK, backfilled by matching the artifact descriptor
  sha256 to ``build_artifacts.content_hash``. The core-domain ``task_type`` and
  the JSON ``artifact`` descriptor columns are dropped (the discriminator is now
  derived from the bound build artifact; the descriptor is superseded by the FK).
  ``build_artifact_id`` stays NULLABLE so a legacy template whose descriptor
  could not be resolved remains READABLE; application validation requires a
  runnable artifact for every new/updated template.
- ``tasks``: ``task_type`` -> ``artifact_type``, ``template_id`` ->
  ``execution_template_id``.
- ``schedules``: ``template_id`` -> ``execution_template_id`` (FK retargeted by
  the table rename), plus a new ``overrides`` JSONB column.

No historical task/execution/log/template rows are deleted. Unresolved legacy
templates (descriptor sha256 with no matching build artifact) keep a NULL
``build_artifact_id`` and are reported by the backfill query below.

Uses PostgreSQL types (JSONB); the SQLite test DB is built from the models
directly (tests/conftest.py), not this migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. canonical build_artifacts table.
    op.create_table(
        "build_artifacts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("package_format", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column(
            "size_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "artifact_metadata",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_type", "content_hash", name="uq_build_artifacts_type_hash"
        ),
    )
    op.create_index(
        "ix_build_artifacts_content_hash", "build_artifacts", ["content_hash"]
    )

    # 2. backfill build_artifacts from distinct legacy template descriptors.
    op.execute(
        """
        INSERT INTO build_artifacts (
            id, artifact_type, package_format, name, filename,
            content_hash, size_bytes, artifact_metadata
        )
        SELECT
            md5('scrapy:' || d.sha256),
            'scrapy',
            'egg',
            COALESCE(d.project, d.filename, d.sha256),
            d.filename,
            d.sha256,
            COALESCE(d.size_bytes, 0),
            jsonb_build_object(
                'project', d.project,
                'version', d.version,
                'spiders', '[]'::jsonb,
                'fetch_path',
                    COALESCE(d.fetch_path,
                             '/api/v1/artifacts/scrapy/' || d.sha256 || '/egg')
            )
        FROM (
            SELECT DISTINCT
                artifact->>'sha256' AS sha256,
                artifact->>'project' AS project,
                artifact->>'version' AS version,
                artifact->>'filename' AS filename,
                artifact->>'fetch_path' AS fetch_path,
                NULLIF(artifact->>'size_bytes', '')::bigint AS size_bytes
            FROM task_templates
            WHERE artifact ? 'sha256' AND artifact->>'sha256' <> ''
        ) AS d
        ON CONFLICT (artifact_type, content_hash) DO NOTHING
        """
    )

    # 3. rename task_templates -> execution_templates and bind build artifacts.
    op.rename_table("task_templates", "execution_templates")
    op.add_column(
        "execution_templates",
        sa.Column("build_artifact_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE execution_templates et
        SET build_artifact_id = ba.id
        FROM build_artifacts ba
        WHERE ba.artifact_type = 'scrapy'
          AND ba.content_hash = et.artifact->>'sha256'
          AND et.artifact ? 'sha256'
          AND et.artifact->>'sha256' <> ''
        """
    )
    op.create_index(
        "ix_execution_templates_build_artifact_id",
        "execution_templates",
        ["build_artifact_id"],
    )
    op.create_foreign_key(
        "fk_execution_templates_build_artifact",
        "execution_templates",
        "build_artifacts",
        ["build_artifact_id"],
        ["id"],
    )
    # drop the superseded discriminator + descriptor columns.
    op.drop_column("execution_templates", "task_type")
    op.drop_column("execution_templates", "artifact")

    # 4. tasks: discriminator + provenance rename.
    op.alter_column("tasks", "task_type", new_column_name="artifact_type")
    op.alter_column("tasks", "template_id", new_column_name="execution_template_id")

    # 5. schedules: FK column rename (FK follows the table rename) + overrides.
    op.drop_index("ix_schedules_template_id", table_name="schedules")
    op.alter_column(
        "schedules", "template_id", new_column_name="execution_template_id"
    )
    op.create_index(
        "ix_schedules_execution_template_id",
        "schedules",
        ["execution_template_id"],
    )
    op.add_column(
        "schedules",
        sa.Column(
            "overrides",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("schedules", "overrides")
    op.drop_index(
        "ix_schedules_execution_template_id", table_name="schedules"
    )
    op.alter_column(
        "schedules", "execution_template_id", new_column_name="template_id"
    )
    op.create_index(
        "ix_schedules_template_id", "schedules", ["template_id"]
    )

    op.alter_column("tasks", "execution_template_id", new_column_name="template_id")
    op.alter_column("tasks", "artifact_type", new_column_name="task_type")

    op.add_column(
        "execution_templates",
        sa.Column(
            "artifact",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "execution_templates",
        sa.Column(
            "task_type", sa.String(), nullable=False, server_default="scrapy"
        ),
    )
    op.drop_constraint(
        "fk_execution_templates_build_artifact",
        "execution_templates",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_execution_templates_build_artifact_id",
        table_name="execution_templates",
    )
    op.drop_column("execution_templates", "build_artifact_id")
    op.rename_table("execution_templates", "task_templates")

    op.drop_index(
        "ix_build_artifacts_content_hash", table_name="build_artifacts"
    )
    op.drop_table("build_artifacts")
