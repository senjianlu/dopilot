"""Test fixtures.

asyncio_mode=auto is provided by the root pyproject. Auth-on/off Settings
variants, an in-memory SQLite session, an httpx ASGI client with the
``get_settings`` / ``get_session`` dependencies overridden, and a programmable
in-process fake of the agent API are provided here.

NOTE: Alembic is the real schema authority for dopilot (PostgreSQL). The
``create_all`` below is TEST-ONLY: it builds the ephemeral SQLite schema from
the ORM models so the suite does not need a real Postgres or the PG-typed
migration.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import dopilot_server.models  # noqa: F401 - register tables on Base.metadata
import pytest
import pytest_asyncio
from dopilot_protocol import (
    AgentRunResponse,
    AgentStatusResponse,
    AgentStopResponse,
    AttemptStatus,
    CleanupResponse,
    EggDeployResponse,
    ExecutionRunRequest,
    TailResponse,
)
from dopilot_server.api.v1.executions import get_request_sessionmaker
from dopilot_server.app import create_app
from dopilot_server.clients.agent import get_agent_client
from dopilot_server.config.loader import get_settings
from dopilot_server.config.settings import Settings
from dopilot_server.db.base import Base
from dopilot_server.db.engine import get_session
from dopilot_server.logs.sse import SubscriptionManager, get_subscriptions
from dopilot_server.models.node import Node
from dopilot_server.services import executions as svc
from dopilot_server.services import states
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def make_settings(auth_on: bool = False, logs_root: str | None = None) -> Settings:
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
            "stream_token_ttl_seconds": 60,
        }
    if logs_root is not None:
        data["logs"] = {
            "root_dir": logs_root,
            # fast cadence so finalize/drain tests don't wait on real intervals
            "eof_stable_seconds": 0,
            "final_drain_hard_timeout_seconds": 1,
            "realtime_drain_interval_seconds": 1,
        }
    return Settings.model_validate(data)


# ---------------------------------------------------------------------------
# fake agent API (duck-types AgentClient; no real agent needed)
# ---------------------------------------------------------------------------


class FakeAgentClient:
    """Programmable in-process fake of the agent surface used by the server."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.raises: dict[str, Exception] = {}
        self.status_script: dict[str, list[AttemptStatus]] = {}
        self.default_status: AttemptStatus = AttemptStatus.running
        self.run_status: AttemptStatus = AttemptStatus.running
        self.exit_codes: dict[str, int] = {}
        self.tail_script: dict[str, list[str]] = {}
        self.tail_finished: dict[str, bool] = {}
        self.deploy_result: EggDeployResponse | None = None
        self.cleaned: list[str] = []

    def _maybe_raise(self, method: str) -> None:
        exc = self.raises.get(method)
        if exc is not None:
            raise exc

    async def run(self, endpoint: str, req) -> AgentRunResponse:
        self.calls.append(("run", req))
        self._maybe_raise("run")
        return AgentRunResponse(
            execution_id=req.execution_id,
            attempt_id=req.attempt_id,
            remote_job_id=f"job-{req.attempt_id[:8]}",
            status=self.run_status,
        )

    async def stop(self, endpoint: str, req) -> AgentStopResponse:
        self.calls.append(("stop", req))
        self._maybe_raise("stop")
        return AgentStopResponse(
            execution_id=req.execution_id,
            attempt_id=req.attempt_id,
            status=AttemptStatus.canceled,
            stopped=True,
        )

    async def status(
        self, endpoint: str, execution_id: str, attempt_id: str
    ) -> AgentStatusResponse:
        self.calls.append(("status", attempt_id))
        self._maybe_raise("status")
        script = self.status_script.get(attempt_id)
        if script:
            value = script.pop(0) if len(script) > 1 else script[0]
        else:
            value = self.default_status
        return AgentStatusResponse(
            execution_id=execution_id,
            attempt_id=attempt_id,
            remote_job_id=f"job-{attempt_id[:8]}",
            status=value,
            exit_code=self.exit_codes.get(attempt_id),
        )

    async def tail(self, endpoint: str, req) -> TailResponse:
        self.calls.append(("tail", (req.attempt_id, req.offset)))
        self._maybe_raise("tail")
        chunks = self.tail_script.get(req.attempt_id)
        finished = self.tail_finished.get(req.attempt_id, True)
        if chunks:
            content = chunks.pop(0)
            end = req.offset + len(content.encode("utf-8"))
            eof = not chunks
            return TailResponse(
                start_offset=req.offset,
                end_offset=end,
                content=content,
                eof=eof,
                finished=eof and finished,
            )
        return TailResponse(
            start_offset=req.offset,
            end_offset=req.offset,
            content="",
            eof=True,
            finished=finished,
        )

    async def cleanup(
        self,
        endpoint: str,
        attempt_id: str,
        execution_id: str | None = None,
        stream: str = "log",
    ) -> CleanupResponse:
        self.calls.append(("cleanup", attempt_id))
        self._maybe_raise("cleanup")
        self.cleaned.append(attempt_id)
        return CleanupResponse(attempt_id=attempt_id, removed=True)

    async def deploy_egg(
        self,
        endpoint: str,
        project: str,
        version: str,
        filename: str,
        egg_bytes: bytes,
    ) -> EggDeployResponse:
        self.calls.append(
            ("deploy_egg", (project, version, filename, len(egg_bytes)))
        )
        self._maybe_raise("deploy_egg")
        if self.deploy_result is not None:
            return self.deploy_result
        return EggDeployResponse(project=project, version=version, spiders=["phase1"])

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    """Auth-OFF settings by default."""
    return make_settings(auth_on=False)


@pytest.fixture
def settings_auth_on() -> Settings:
    """Auth-ON settings variant."""
    return make_settings(auth_on=True)


@pytest.fixture
def logs_root(tmp_path) -> str:
    return str(tmp_path / "server-logs")


@pytest.fixture
def exec_settings(logs_root: str) -> Settings:
    return make_settings(auth_on=False, logs_root=logs_root)


@pytest.fixture
def exec_settings_auth_on(logs_root: str) -> Settings:
    return make_settings(auth_on=True, logs_root=logs_root)


@pytest.fixture
def fake_agent() -> FakeAgentClient:
    return FakeAgentClient()


@pytest.fixture
def subscriptions() -> SubscriptionManager:
    return SubscriptionManager()


class Seeder:
    """Helpers to seed nodes + running executions for integration tests."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def healthy_node(
        self,
        agent_id: str = "agent-1",
        endpoint: str = "http://agent:6800",
        scrapy: bool = True,
        status: str = "healthy",
    ) -> Node:
        node = Node(
            id=uuid.uuid4(),
            agent_id=agent_id,
            endpoint=endpoint,
            status=status,
            capabilities={"scrapy": scrapy},
            health={"scrapyd": {"running": True, "port": 6801}},
        )
        self.session.add(node)
        await self.session.commit()
        return node

    async def running_execution(self, node: Node | None = None):
        """Create a running execution + one running attempt + active log file."""
        if node is None:
            node = await self.healthy_node()
        req = ExecutionRunRequest(
            task_type="scrapy",
            target="demo:phase1",
            node_strategy="all",
            params={"project": "demo", "spider": "phase1"},
        )
        execution = svc.create_execution(self.session, req)
        execution.status = states.EXEC_RUNNING
        attempt = svc.create_attempt(self.session, execution, node)
        attempt.status = states.ATTEMPT_RUNNING
        attempt.remote_job_id = "job-x"
        log_file = svc.create_log_file(
            self.session, self.settings, execution, attempt
        )
        await self.session.commit()
        return execution, attempt, log_file


@pytest.fixture
def seeder(db_session: AsyncSession, exec_settings: Settings) -> Seeder:
    return Seeder(db_session, exec_settings)


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """In-memory SQLite engine with the ORM schema created (test-only).

    StaticPool shares the single in-memory connection across all sessions built
    from this engine, so a request session and the SSE endpoint's short-lived
    preflight session see the same data.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # TEST-ONLY: Alembic owns the real schema; here we materialize the
        # ephemeral test DB straight from the models.
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with maker() as session:
        yield session


@pytest.fixture
def test_sessionmaker(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession
    )


def _build_client(app_settings: Settings, session: AsyncSession) -> AsyncClient:
    app = create_app(app_settings)
    app.dependency_overrides[get_settings] = lambda: app_settings

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _build_exec_client(
    app_settings: Settings,
    session: AsyncSession,
    agent: FakeAgentClient,
    subs: SubscriptionManager,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncClient:
    app = create_app(app_settings)
    app.state.subscriptions = subs
    app.dependency_overrides[get_settings] = lambda: app_settings

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    # SSE preflight uses its own short-lived session from this sessionmaker
    # (bound to the same StaticPool engine, so it sees seeded data).
    app.dependency_overrides[get_request_sessionmaker] = lambda: sessionmaker
    app.dependency_overrides[get_agent_client] = lambda: agent
    app.dependency_overrides[get_subscriptions] = lambda: subs
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


@pytest_asyncio.fixture
async def exec_client(
    exec_settings: Settings,
    db_session: AsyncSession,
    fake_agent: FakeAgentClient,
    subscriptions: SubscriptionManager,
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Auth-OFF client wired to the fake agent + a temp log root."""
    async with _build_exec_client(
        exec_settings, db_session, fake_agent, subscriptions, test_sessionmaker
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def exec_client_auth_on(
    exec_settings_auth_on: Settings,
    db_session: AsyncSession,
    fake_agent: FakeAgentClient,
    subscriptions: SubscriptionManager,
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Auth-ON client wired to the fake agent + a temp log root."""
    async with _build_exec_client(
        exec_settings_auth_on,
        db_session,
        fake_agent,
        subscriptions,
        test_sessionmaker,
    ) as ac:
        yield ac
