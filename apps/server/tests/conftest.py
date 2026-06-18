"""Test fixtures.

asyncio_mode=auto is provided by the root pyproject. Auth-on/off Settings
variants, an in-memory SQLite session, and an httpx ASGI client with the
``get_settings`` / ``get_session`` dependencies overridden are provided here.

NOTE: Alembic is the real schema authority for dopilot (PostgreSQL). The
``create_all`` below is TEST-ONLY: it builds the ephemeral SQLite schema from
the ORM models so the suite does not need a real Postgres or the PG-typed
migration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import dopilot_server.models  # noqa: F401 - register tables on Base.metadata
import pytest
import pytest_asyncio
from dopilot_server.app import create_app
from dopilot_server.config.loader import get_settings
from dopilot_server.config.settings import Settings
from dopilot_server.db.base import Base
from dopilot_server.db.engine import get_session
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_settings(auth_on: bool = False) -> Settings:
    """Build a test :class:`Settings` (auth on/off variants)."""
    data: dict = {
        "database": {"url": "sqlite+aiosqlite:///:memory:"},
        "nodes": {"agents": []},
    }
    if auth_on:
        data["auth"] = {
            "admin_username": "admin",
            "admin_password": "secret",
            "token_secret": "test-secret-key",
            "access_token_ttl_minutes": 60,
        }
    return Settings.model_validate(data)


@pytest.fixture
def settings() -> Settings:
    """Auth-OFF settings by default."""
    return make_settings(auth_on=False)


@pytest.fixture
def settings_auth_on() -> Settings:
    """Auth-ON settings variant."""
    return make_settings(auth_on=True)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite session with the ORM schema created (test-only)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        # TEST-ONLY: Alembic owns the real schema; here we materialize the
        # ephemeral test DB straight from the models.
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(
        bind=engine, expire_on_commit=False, class_=AsyncSession
    )
    async with maker() as session:
        yield session
    await engine.dispose()


def _build_client(app_settings: Settings, session: AsyncSession) -> AsyncClient:
    app = create_app(app_settings)
    app.dependency_overrides[get_settings] = lambda: app_settings

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def client(
    settings: Settings, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """Auth-OFF ASGI client sharing the test ``db_session``."""
    async with _build_client(settings, db_session) as ac:
        yield ac


@pytest_asyncio.fixture
async def client_auth_on(
    settings_auth_on: Settings, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """Auth-ON ASGI client sharing the test ``db_session``."""
    async with _build_client(settings_auth_on, db_session) as ac:
        yield ac
