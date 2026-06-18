"""Alembic environment.

Schema authority: Alembic is the ONLY thing that creates dopilot's tables — the
app never calls ``Base.metadata.create_all()``.

DB URL resolution: ``DOPILOT_DATABASE_URL`` if set, else ``[database].url`` from
the ``DOPILOT_CONFIG`` TOML. Migrations use a SYNC engine with the same psycopg
(psycopg3) driver as the async app (``postgresql+psycopg://``).
"""

from __future__ import annotations

import os
import tomllib
from logging.config import fileConfig
from pathlib import Path

import dopilot_server.models  # noqa: F401
from alembic import context

# Import models so every table is registered on Base.metadata.
from dopilot_server.db.base import Base
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    env_url = os.environ.get("DOPILOT_DATABASE_URL")
    if env_url:
        return env_url

    config_path = os.environ.get("DOPILOT_CONFIG")
    if config_path:
        path = Path(config_path)
        if path.is_file():
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            url = (data.get("database") or {}).get("url")
            if url:
                return url

    raise RuntimeError(
        "No database URL: set DOPILOT_DATABASE_URL or provide DOPILOT_CONFIG "
        "with a [database].url."
    )


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB using a SYNC engine."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
