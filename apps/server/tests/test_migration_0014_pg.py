"""Migration 0014 against a REAL PostgreSQL: backfill + index + rollback.

Reading the migration source only proves it was written; it cannot catch a bad
revision chain, a ``server_default`` that never lands on existing rows, or a
downgrade that does not undo what it added. This runs Alembic for real.

Database lifecycle: the other PostgreSQL tests build their schema with
``Base.metadata.create_all`` and tear it down with ``drop_all`` — neither of
which touches ``alembic_version``. Interleaved with this test that leaves
"stamped 0013 but the tables are gone", and the upgrade would then fail at
``ALTER TABLE schedules``. So this test owns its own baseline: hard-reset the
schema (which drops ``alembic_version`` too), migrate up to 0013, and hard-reset
again afterwards into the ``create_all`` shape the other fixtures expect. It is
therefore order-independent and repeatable.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from dopilot_server.db.base import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .conftest import PG_TEST_URL

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _alembic(command_name: str, revision: str) -> None:
    """Run one Alembic command synchronously (called via ``to_thread``).

    Built WITHOUT the ini path on purpose: ``migrations/env.py`` calls
    ``fileConfig(config.config_file_name)`` when one is set, and that reconfigures
    global logging with ``disable_existing_loggers`` — which silently kills every
    later ``caplog`` assertion in the same pytest session. With no config file the
    env script skips that branch; ``script_location`` is supplied directly and the
    URL comes from ``DOPILOT_DATABASE_URL``.
    """
    from alembic import command as alembic_command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    getattr(alembic_command, command_name)(cfg, revision)


async def _reset_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture
async def migration_db():
    if not PG_TEST_URL:
        pytest.fail(
            "DOPILOT_TEST_DATABASE_URL is not set: the migration test must run "
            "against scripts/dev-db.sh (it is not allowed to skip)"
        )
    previous = os.environ.get("DOPILOT_DATABASE_URL")
    os.environ["DOPILOT_DATABASE_URL"] = PG_TEST_URL
    engine = create_async_engine(PG_TEST_URL)
    await _reset_schema(engine)
    await asyncio.to_thread(_alembic, "upgrade", "0013")
    try:
        yield engine
    finally:
        # Hand the database back in the shape the other PG fixtures expect.
        await _reset_schema(engine)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
        if previous is None:
            os.environ.pop("DOPILOT_DATABASE_URL", None)
        else:
            os.environ["DOPILOT_DATABASE_URL"] = previous


async def test_migration_0014_backfills_and_indexes(migration_db):
    engine = migration_db

    # Pre-upgrade rows, written with the 0013 schema (no max_concurrency).
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO execution_templates (id, name, node_strategy, node_ids,"
                " created_at, updated_at)"
                " VALUES ('t1', 'legacy-template', 'all', '[]', now(), now())"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO schedules (id, name, enabled, execution_template_id,"
                " trigger_type, interval_seconds, overrides, consecutive_error_count,"
                " outcome_generation, created_at, updated_at)"
                " VALUES ('s1', 'legacy-schedule', true, 't1', 'interval', 60, '{}',"
                " 0, 0, now(), now())"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO tasks (id, artifact_type, target, node_strategy, source,"
                " schedule_id, template_snapshot, status, status_detail, params,"
                " created_at)"
                " VALUES ('k1', 'scrapy', 'demo:phase1', 'all', 'schedule_timer',"
                " 's1', '{}', 'running', '{}', '{}', now())"
            )
        )

    await asyncio.to_thread(_alembic, "upgrade", "0014")

    async with engine.connect() as conn:
        value = (
            await conn.execute(
                text("SELECT max_concurrency FROM schedules WHERE id = 's1'")
            )
        ).scalar_one()
        # The server_default has to reach EXISTING rows; an ORM-only default
        # would leave this NULL / fail the NOT NULL constraint.
        assert value == 1

        indexes = (
            (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'tasks'")
                )
            )
            .scalars()
            .all()
        )
        assert "ix_tasks_schedule_id_status" in indexes

    await asyncio.to_thread(_alembic, "downgrade", "0013")

    async with engine.connect() as conn:
        columns = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'schedules'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "max_concurrency" not in columns
        indexes = (
            (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'tasks'")
                )
            )
            .scalars()
            .all()
        )
        assert "ix_tasks_schedule_id_status" not in indexes
