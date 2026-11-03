"""Migration 0016 against a REAL PostgreSQL: the circuit-breaker columns (decision
0025), their nullability / server defaults on existing rows, and rollback.

Reading the migration source only proves it was written; it cannot catch a
broken revision chain or a downgrade that does not undo what it added.

Database lifecycle mirrors ``test_migration_0015_pg.py``: this test owns its own
baseline (hard-reset the schema, migrate up to 0015) and hands the database back
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
SCHEDULE_COLUMNS = {
    "breaker_state", "breaker_level", "breaker_opened_at", "breaker_retry_at",
    "breaker_escalated_at", "breaker_reason", "breaker_artifact_id",
}
NOT_NULL = {"breaker_state", "breaker_level"}


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


async def _columns(engine, table: str) -> dict[str, str]:
    """``column_name -> is_nullable`` for ``table``."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns"
                    " WHERE table_name = :t"
                ),
                {"t": table},
            )
        ).all()
    return dict(rows)


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
    await asyncio.to_thread(_alembic, "upgrade", "0015")
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


async def test_migration_0016_adds_and_drops_breaker_columns(migration_db):
    engine = migration_db
    assert SCHEDULE_COLUMNS & set(await _columns(engine, "schedules")) == set()

    # Rows written under 0015: one ordinary schedule and one auto-disabled under
    # 0021 (enabled=false + auto_disabled_*), which the upgrade must not touch.
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
                " outcome_generation, max_concurrency, created_at, updated_at)"
                " VALUES ('s1', 'live-schedule', true, 't1', 'interval', 60, '{}',"
                " 0, 0, 1, now(), now())"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO schedules (id, name, enabled, execution_template_id,"
                " trigger_type, interval_seconds, overrides, consecutive_error_count,"
                " auto_disabled_at, auto_disabled_reason, outcome_generation,"
                " max_concurrency, created_at, updated_at)"
                " VALUES ('s2', 'auto-disabled-schedule', false, 't1', 'interval', 60,"
                " '{}', 5, '2026-10-31T19:46:00+00:00',"
                " '{\"consecutive_errors\": 5, \"threshold\": 5}', 2, 1, now(), now())"
            )
        )

    await asyncio.to_thread(_alembic, "upgrade", "0016")

    schedule_cols = await _columns(engine, "schedules")
    assert SCHEDULE_COLUMNS <= set(schedule_cols)
    for col in SCHEDULE_COLUMNS:
        assert schedule_cols[col] == ("NO" if col in NOT_NULL else "YES"), col
    assert (await _columns(engine, "schedule_outcome_ledger"))["outcome_class"] == "YES"
    assert (await _columns(engine, "executions"))["outcome_class"] == "YES"

    async with engine.connect() as conn:
        rows = {
            r.id: r
            for r in (
                await conn.execute(
                    text(
                        "SELECT id, enabled, breaker_state, breaker_level, breaker_reason,"
                        " consecutive_error_count, auto_disabled_at, auto_disabled_reason,"
                        " outcome_generation FROM schedules"
                    )
                )
            ).all()
        }
    for sid in ("s1", "s2"):
        assert rows[sid].breaker_state == "closed" and rows[sid].breaker_level == 0, sid
        assert rows[sid].breaker_reason is None
    legacy = rows["s2"]
    assert legacy.enabled is False and legacy.consecutive_error_count == 5
    assert legacy.auto_disabled_at is not None
    assert legacy.auto_disabled_reason == {"consecutive_errors": 5, "threshold": 5}
    assert legacy.outcome_generation == 2

    await asyncio.to_thread(_alembic, "downgrade", "0015")

    assert SCHEDULE_COLUMNS & set(await _columns(engine, "schedules")) == set()
    assert "outcome_class" not in await _columns(engine, "schedule_outcome_ledger")
    assert "outcome_class" not in await _columns(engine, "executions")

    await asyncio.to_thread(_alembic, "upgrade", "0016")
    assert SCHEDULE_COLUMNS <= set(await _columns(engine, "schedules"))
