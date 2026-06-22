"""phase 2.2: unique execution-template + schedule names

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-22

Phase 2.2 (see docs/phases/phase-2.2/00-brief.md). Adds uniqueness to
``execution_templates.name`` and ``schedules.name`` so the create/rename paths
can return a deterministic 409 conflict (the service checks first; the DB
constraint is the backstop).

Existing rows are PRESERVED: before adding each unique constraint we
deterministically rename duplicate rows to ``<old-name>__duplicate__<id-prefix>``
keeping the earliest (created_at, id) row's original name. This is idempotent in
spirit — the renamed value embeds the row id, so re-running on already-unique
data is a no-op.

PostgreSQL is the real schema authority; the SQLite test DB is built from the
models directly (tests/conftest.py), where ``unique=True`` on the mapped columns
provides the same constraint.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dedupe(table: str) -> None:
    # Rename every non-first row sharing a name. ROW_NUMBER orders by
    # (created_at, id) so the oldest row keeps its name; ties break on id.
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY name ORDER BY created_at, id
                   ) AS rn
            FROM {table}
        )
        UPDATE {table} AS t
        SET name = t.name || '__duplicate__' || substr(t.id, 1, 8)
        FROM ranked
        WHERE t.id = ranked.id AND ranked.rn > 1
        """
    )


def upgrade() -> None:
    _dedupe("execution_templates")
    _dedupe("schedules")
    op.create_unique_constraint(
        "uq_execution_templates_name", "execution_templates", ["name"]
    )
    op.create_unique_constraint("uq_schedules_name", "schedules", ["name"])


def downgrade() -> None:
    op.drop_constraint("uq_schedules_name", "schedules", type_="unique")
    op.drop_constraint(
        "uq_execution_templates_name", "execution_templates", type_="unique"
    )
