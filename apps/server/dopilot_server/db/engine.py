"""Async engine + session factory.

Engine creation is lazy and cached per-URL so tests can either override the
``get_session`` dependency wholesale or build their own engine. The app uses
the SQLAlchemy 2.x async engine with the psycopg (psycopg3) driver
(``postgresql+psycopg://``); Alembic uses a SYNC engine with the same driver.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Cache of engines / sessionmakers keyed by database URL. Lazy so that simply
# importing this module (e.g. during py_compile or unit tests) does not open a
# connection pool.
_engines: dict[str, AsyncEngine] = {}
_sessionmakers: dict[str, async_sessionmaker[AsyncSession]] = {}


def get_engine(url: str) -> AsyncEngine:
    """Return (creating on first use) the async engine for ``url``."""
    engine = _engines.get(url)
    if engine is None:
        engine = create_async_engine(url, pool_pre_ping=True, future=True)
        _engines[url] = engine
    return engine


def get_sessionmaker(url: str) -> async_sessionmaker[AsyncSession]:
    """Return (creating on first use) the session factory for ``url``."""
    maker = _sessionmakers.get(url)
    if maker is None:
        maker = async_sessionmaker(
            bind=get_engine(url),
            expire_on_commit=False,
            class_=AsyncSession,
        )
        _sessionmakers[url] = maker
    return maker


async def dispose_engines() -> None:
    """Dispose all cached engines (called from the app lifespan shutdown)."""
    for engine in _engines.values():
        await engine.dispose()
    _engines.clear()
    _sessionmakers.clear()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an :class:`AsyncSession`.

    The real session factory is resolved from app state in
    :mod:`dopilot_server.app`; this default implementation is overridden there
    (and in tests) via ``app.dependency_overrides``. It is intentionally a thin
    placeholder so the dependency symbol exists for overriding.
    """
    raise RuntimeError(
        "get_session must be overridden by the app lifespan / dependency "
        "override before use."
    )


async def ping(session: AsyncSession) -> bool:
    """Run ``SELECT 1`` and return True on success, False on any failure."""
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check must never raise
        return False
