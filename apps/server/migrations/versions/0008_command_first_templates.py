"""phase 1.8.1: command-first execution templates + schedule overrides

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-20

Destructive command-first refactor (see docs/phases/phase-1.8.1/00-brief.md):

- ``execution_templates`` gains a nullable ``command`` column. It is best-effort
  BACKFILLED by synthesizing ``scrapy crawl <spider> [-a k=v]... [-s K=V]...``
  from the legacy decomposed ``spider`` / ``args`` / ``settings`` columns. Rows
  with no spider keep ``command`` NULL (migration safety); application validation
  requires a valid command for every new/updated template afterwards.
- The legacy decomposed columns ``spider`` / ``settings`` / ``args`` are then
  DROPPED — they are no longer a product or protocol concept.
- ``schedules.overrides`` has the legacy ``spider`` / ``settings`` / ``args``
  keys STRIPPED (command overrides are the only execution-param override now).

This is destructive: the decomposed values are not preserved after the drop, and
the synthesized command does NOT shell-quote values containing whitespace
(best-effort). In-flight old Redis run commands are incompatible with the new
agent payload; drain active/queued commands before deploying.

Uses PostgreSQL types (JSONB); the SQLite test DB is built from the models
directly (tests/conftest.py), not this migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. add the command column (nullable for migration safety).
    op.add_column(
        "execution_templates",
        sa.Column("command", sa.String(), nullable=True),
    )

    # 2. best-effort backfill: synthesize a canonical command from the legacy
    #    decomposed spider/args/settings. Rows without a spider stay NULL.
    op.execute(
        """
        UPDATE execution_templates SET command =
            'scrapy crawl ' || spider
            || COALESCE(
                (SELECT string_agg(' -a ' || a.key || '=' || a.value, '')
                 FROM jsonb_each_text(args) AS a), '')
            || COALESCE(
                (SELECT string_agg(' -s ' || s.key || '=' || s.value, '')
                 FROM jsonb_each_text(settings) AS s), '')
        WHERE spider IS NOT NULL AND spider <> ''
        """
    )

    # 3. drop the superseded decomposed columns.
    op.drop_column("execution_templates", "spider")
    op.drop_column("execution_templates", "settings")
    op.drop_column("execution_templates", "args")

    # 4. strip the legacy execution-param keys from schedule overrides.
    op.execute(
        """
        UPDATE schedules
        SET overrides = (overrides - 'spider' - 'settings' - 'args')
        WHERE overrides ?| array['spider', 'settings', 'args']
        """
    )


def downgrade() -> None:
    # Re-add the decomposed columns (data is not recoverable from command).
    op.add_column(
        "execution_templates",
        sa.Column("spider", sa.String(), nullable=True),
    )
    op.add_column(
        "execution_templates",
        sa.Column(
            "settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "execution_templates",
        sa.Column(
            "args",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.drop_column("execution_templates", "command")
