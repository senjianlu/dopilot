"""phase 2a: id naming clean-cut (execution_id/attempt_id -> task_id/execution_id)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-20

Phase 2a (see docs/phases/phase-2a/00-brief.md). Collapses the wire/disk/DB seam
so the Redis payloads, on-disk log paths, agent state files, and these index
tables all use the same ids as the server domain:

    old seam: execution_id = Task.id, attempt_id = Execution.id
    new:      task_id      = Task.id, execution_id = Execution.id

This renames the seam columns (and their indexes) on the three index tables that
carried the old names:

- ``execution_log_files``: PK ``(execution_id, attempt_id, stream)`` ->
  ``(task_id, execution_id, stream)`` (the PK constraint tracks the renamed
  columns automatically; no drop/recreate needed).
- ``command_outbox``: ``execution_id`` -> ``task_id``, ``attempt_id`` ->
  ``execution_id`` (+ rename indexes).
- ``event_audit``: ``attempt_id`` -> ``execution_id`` (+ rename index).

Data-preserving ``RENAME COLUMN`` + index rename, same style as 0004. (dopilot
is greenfield/single-admin with no production data, but the rename costs nothing
to keep.) The SQLite test DB is built from the models directly
(tests/conftest.py), not this migration; PostgreSQL is the real schema authority.

⚠️ Each table's two-column swap renames the *old* ``execution_id`` to ``task_id``
FIRST, then the *old* ``attempt_id`` to ``execution_id`` — otherwise the second
rename would collide with the still-present ``execution_id`` column.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- execution_log_files: (execution_id, attempt_id) -> (task_id, execution_id)
    op.execute(
        "ALTER TABLE execution_log_files RENAME COLUMN execution_id TO task_id"
    )
    op.execute(
        "ALTER TABLE execution_log_files RENAME COLUMN attempt_id TO execution_id"
    )

    # --- command_outbox: rename indexes around the column swap ---------------
    op.drop_index("ix_command_outbox_execution_id", table_name="command_outbox")
    op.drop_index("ix_command_outbox_attempt_id", table_name="command_outbox")
    op.execute("ALTER TABLE command_outbox RENAME COLUMN execution_id TO task_id")
    op.execute("ALTER TABLE command_outbox RENAME COLUMN attempt_id TO execution_id")
    op.create_index("ix_command_outbox_task_id", "command_outbox", ["task_id"])
    op.create_index(
        "ix_command_outbox_execution_id", "command_outbox", ["execution_id"]
    )

    # --- event_audit: attempt_id -> execution_id ----------------------------
    op.drop_index("ix_event_audit_attempt_id", table_name="event_audit")
    op.execute("ALTER TABLE event_audit RENAME COLUMN attempt_id TO execution_id")
    op.create_index("ix_event_audit_execution_id", "event_audit", ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_event_audit_execution_id", table_name="event_audit")
    op.execute("ALTER TABLE event_audit RENAME COLUMN execution_id TO attempt_id")
    op.create_index("ix_event_audit_attempt_id", "event_audit", ["attempt_id"])

    op.drop_index("ix_command_outbox_execution_id", table_name="command_outbox")
    op.drop_index("ix_command_outbox_task_id", table_name="command_outbox")
    op.execute("ALTER TABLE command_outbox RENAME COLUMN execution_id TO attempt_id")
    op.execute("ALTER TABLE command_outbox RENAME COLUMN task_id TO execution_id")
    op.create_index(
        "ix_command_outbox_execution_id", "command_outbox", ["execution_id"]
    )
    op.create_index(
        "ix_command_outbox_attempt_id", "command_outbox", ["attempt_id"]
    )

    op.execute(
        "ALTER TABLE execution_log_files RENAME COLUMN execution_id TO attempt_id"
    )
    op.execute(
        "ALTER TABLE execution_log_files RENAME COLUMN task_id TO execution_id"
    )
