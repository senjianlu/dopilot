"""Migration 0015 against a REAL PostgreSQL: the progress columns and rollback.

Reading the migration source only proves it was written; it cannot catch a
broken revision chain or a downgrade that does not undo what it added.

Database lifecycle mirrors ``test_migration_0014_pg.py``: this test owns its own
baseline (hard-reset the schema, migrate up to 0014) and hands the database back
in the ``create_all`` shape the other PG fixtures expect, so it is
order-independent and repeatable.
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
NEW_COLUMNS = {"last_progress_at", "last_progress_sample_at", "no_progress_at"}


def _alembic(command_name: str, revision: str) -> None:
    # No ini path on purpose: migrations/env.py would call fileConfig() and
    # reconfigure global logging, killing caplog for the rest of the session.
    from alembic import command as alembic_command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    getattr(alembic_command, command_name)(cfg, revision)


async def _reset_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def _execution_columns(engine) -> set[str]:
    async with engine.connect() as conn:
        return set(
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'executions'"
                    )
                )
            )
            .scalars()
            .all()
        )


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
    await asyncio.to_thread(_alembic, "upgrade", "0014")
    try:
        yield engine
    finally:
        await _reset_schema(engine)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
        if previous is None:
            os.environ.pop("DOPILOT_DATABASE_URL", None)
        else:
            os.environ["DOPILOT_DATABASE_URL"] = previous


async def test_migration_0015_adds_and_drops_progress_columns(migration_db):
    # TC-34
    engine = migration_db
    assert NEW_COLUMNS & await _execution_columns(engine) == set()

    # A row written under 0014 must survive the upgrade with NULL progress: no
    # backfill is wanted, and the detector requires a FRESH sample before it
    # judges anything, so pre-existing rows are skipped rather than mis-flagged.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tasks (id, artifact_type, target, node_strategy,"
                " source, template_snapshot, status, status_detail, params,"
                " created_at)"
                " VALUES ('k1', 'scrapy', 'demo:phase1', 'all', 'manual', '{}',"
                " 'running', '{}', '{}', now())"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO executions (id, task_id, agent_id, status,"
                " error_detail, created_at, updated_at)"
                " VALUES ('x1', 'k1', 'agent-1', 'running', '{}', now(), now())"
            )
        )

    await asyncio.to_thread(_alembic, "upgrade", "0015")

    assert NEW_COLUMNS <= await _execution_columns(engine)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT last_progress_at, last_progress_sample_at,"
                    " no_progress_at FROM executions WHERE id = 'x1'"
                )
            )
        ).one()
    assert row == (None, None, None)

    await asyncio.to_thread(_alembic, "downgrade", "0014")

    assert NEW_COLUMNS & await _execution_columns(engine) == set()
