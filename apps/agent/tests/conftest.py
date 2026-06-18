"""Shared pytest fixtures for the agent test suite.

Provides an in-process ASGI client (httpx + ASGITransport) with ``get_settings``
overridden to a test :class:`Settings`, plus helpers to build clients for both
auth modes (shared_token set vs empty).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from dopilot_agent.config.loader import get_settings
from dopilot_agent.config.settings import (
    AgentSettings,
    AuthSettings,
    Capabilities,
    Settings,
)
from dopilot_agent.main import create_app
from httpx import ASGITransport, AsyncClient

BASE_URL = "http://agent.test"
TEST_TOKEN = "test-shared-token"


def make_settings(shared_token: str = "") -> Settings:
    return Settings(
        agent=AgentSettings(
            agent_id="agent-test-1",
            host="127.0.0.1",
            port=6810,
            workdir="/agent-data/test",
        ),
        auth=AuthSettings(shared_token=shared_token),
        capabilities=Capabilities(scrapy=True, script=True, docker=False),
    )


def build_client(settings: Settings) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url=BASE_URL)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Default client: auth OFF (empty shared token)."""
    async with build_client(make_settings(shared_token="")) as ac:
        yield ac


@pytest_asyncio.fixture
async def client_auth() -> AsyncIterator[AsyncClient]:
    """Client with shared-token auth ENABLED."""
    async with build_client(make_settings(shared_token=TEST_TOKEN)) as ac:
        yield ac


@pytest.fixture
def client_factory() -> Callable[[str], AsyncClient]:
    """Factory to build a client for an arbitrary shared token."""

    def _factory(shared_token: str = "") -> AsyncClient:
        return build_client(make_settings(shared_token=shared_token))

    return _factory
