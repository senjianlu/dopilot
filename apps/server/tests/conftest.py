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
from datetime import UTC, datetime, timedelta
from typing import Any

import dopilot_server.models  # noqa: F401 - register tables on Base.metadata
import fakeredis.aioredis as fakeaioredis
import pytest
import pytest_asyncio
from dopilot_protocol import ExecutionRunRequest
from dopilot_server.api.v1.tasks import get_dispatcher, get_request_sessionmaker
from dopilot_server.app import create_app
from dopilot_server.config.loader import get_settings
from dopilot_server.config.settings import RedisSettings, Settings
from dopilot_server.db.base import Base
from dopilot_server.db.engine import get_session
from dopilot_server.logs.sse import SubscriptionManager, get_subscriptions
from dopilot_server.models.node import Node
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.services import executions as svc
from dopilot_server.services import states
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def make_settings(
    auth_on: bool = False,
    logs_root: str | None = None,
    artifacts_root: str | None = None,
) -> Settings:
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
    if artifacts_root is not None:
        data["artifacts"] = {"root_dir": artifacts_root}
    return Settings.model_validate(data)


# ---------------------------------------------------------------------------
# fake Redis Streams (real consumer-group fidelity via fakeredis; faults
# injected via flags). Satisfies the narrow RedisStreamClient surface used by
# the producer / dispatcher / consumers.
# ---------------------------------------------------------------------------


class FakeRedisStreams:
    """In-memory Redis Streams double backed by ``fakeredis.aioredis``.

    Pass ``server=`` (a ``fakeredis.FakeServer``) to share one in-memory store
    across several clients (e.g. a server-side and an agent-side view in one
    test). Set ``fail_xadd`` / ``fail_streams`` to simulate Redis being
    unavailable for publishing.
    """

    def __init__(self, *, server: Any = None) -> None:
        kwargs: dict[str, Any] = {"decode_responses": False}
        if server is not None:
            kwargs["server"] = server
        self._c = fakeaioredis.FakeRedis(**kwargs)
        self.server = server
        self.fail_xadd = False
        self.fail_streams: set[str] = set()
        self.calls: list[tuple[str, Any]] = []

    async def xadd(
        self,
        stream: str,
        fields: dict[Any, Any],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> Any:
        self.calls.append(("xadd", stream))
        if self.fail_xadd or stream in self.fail_streams:
            raise RedisConnectionError("fake redis: xadd disabled")
        return await self._c.xadd(stream, fields, maxlen=maxlen, approximate=approximate)

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> Any:
        return await self._c.xreadgroup(group, consumer, streams, count=count, block=block)

    async def xack(self, stream: str, group: str, *ids: Any) -> int:
        return await self._c.xack(stream, group, *ids)

    async def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str = "0-0",
        *,
        count: int = 100,
    ) -> Any:
        return await self._c.xautoclaim(stream, group, consumer, min_idle_ms, start, count=count)

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._c.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:  # BUSYGROUP if it already exists
            if "BUSYGROUP" not in str(exc):
                raise

    async def xlen(self, stream: str) -> int:
        return await self._c.xlen(stream)

    async def xinfo_stream(self, stream: str) -> dict[str, Any]:
        try:
            return await self._c.xinfo_stream(stream)
        except Exception as exc:  # noqa: BLE001 - mirror RedisStreams' mapping
            if "no such key" in str(exc).lower():
                return {"length": 0, "first-entry": None}
            raise

    async def info(self, section: str | None = None) -> dict[str, Any]:
        return await (self._c.info() if section is None else self._c.info(section))

    async def xtrim(self, stream, *, minid=None, maxlen=None, approximate=True) -> int:
        self.calls.append(("xtrim", stream))
        if minid is not None:
            return await self._c.xtrim(stream, minid=minid, approximate=approximate)
        return await self._c.xtrim(stream, maxlen=maxlen, approximate=approximate)

    # Log-flood guard double for MEMORY USAGE: fakeredis has no allocator view,
    # so estimate = sum of every entry's field bytes + 64B per-entry overhead.
    # ``memory_usage_override`` lets a test pin the reported value (e.g. to
    # simulate a stream that never converges).
    memory_usage_override: int | None = None
    memory_usage_calls: int = 0

    async def memory_usage(self, key: str, *, samples: int = 0) -> int | None:
        self.memory_usage_calls += 1
        if self.memory_usage_override is not None:
            return self.memory_usage_override
        if not await self._c.exists(key):
            return None
        total = 0
        for _id, fields in await self._c.xrange(key):
            total += 64 + sum(len(k) + len(v) for k, v in fields.items())
        return total

    async def scan_keys(self, pattern: str) -> list[str]:
        out = []
        async for key in self._c.scan_iter(match=pattern, count=200):
            out.append(key.decode() if isinstance(key, bytes) else str(key))
        return out

    async def delete(self, *keys: str) -> int:
        self.calls.append(("delete", ",".join(keys)))
        return int(await self._c.delete(*keys)) if keys else 0

    async def xrange(self, stream: str, min_id: str, max_id: str, *, count: int = 1) -> Any:
        return await self._c.xrange(stream, min=min_id, max=max_id, count=count)

    async def aclose(self) -> None:
        await self._c.aclose()

    # --- test-only helpers -------------------------------------------------
    async def entries(self, stream: str) -> list[tuple[Any, dict[Any, Any]]]:
        """All entries of ``stream`` as ``[(id, fields), ...]`` for assertions."""
        return await self._c.xrange(stream)

    async def pending_count(self, stream: str, group: str) -> int:
        info = await self._c.xpending(stream, group)
        return int(info["pending"]) if info else 0


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_server() -> Any:
    """A shared ``fakeredis.FakeServer`` to back several FakeRedisStreams views."""
    import fakeredis

    return fakeredis.FakeServer()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[Any]:
    """Factory building FakeRedisStreams instances, all closed on teardown."""
    created: list[FakeRedisStreams] = []

    def _make(*, server: Any = None) -> FakeRedisStreams:
        fr = FakeRedisStreams(server=server)
        created.append(fr)
        return fr

    yield _make
    for fr in created:
        await fr.aclose()


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
def artifacts_root(tmp_path) -> str:
    return str(tmp_path / "server-artifacts")


@pytest.fixture
def exec_settings(logs_root: str, artifacts_root: str) -> Settings:
    return make_settings(
        auth_on=False, logs_root=logs_root, artifacts_root=artifacts_root
    )


@pytest.fixture
def exec_settings_auth_on(logs_root: str, artifacts_root: str) -> Settings:
    return make_settings(
        auth_on=True, logs_root=logs_root, artifacts_root=artifacts_root
    )


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
        script: bool = False,
        status: str = "healthy",
        last_seen_age_seconds: float = 0.0,
    ) -> Node:
        # Phase 1.5: node selection is heartbeat-recency based, so a "healthy"
        # node must carry a fresh last_seen_at. last_seen_age_seconds backdates
        # it (e.g. to test heartbeat-timeout exclusion).
        # Phase 2b: ``script`` advertises the python_wheel capability.
        last_seen = datetime.now(UTC) - timedelta(seconds=last_seen_age_seconds)
        node = Node(
            id=uuid.uuid4(),
            agent_id=agent_id,
            endpoint=endpoint,
            status=status,
            capabilities={"scrapy": scrapy, "script": script},
            health={
                "scrapyd": {"running": True, "port": 6801},
                "redis": {
                    "connected": True,
                    "command_consumer": {"running": True},
                },
            },
            last_seen_at=last_seen,
        )
        self.session.add(node)
        await self.session.commit()
        return node

    async def build_artifact(
        self,
        *,
        project: str = "demo",
        spiders: tuple[str, ...] = ("phase1",),
        sha256: str = "a" * 64,
        artifact_type: str = "scrapy",
        package_format: str = "egg",
    ):
        """Seed a canonical build artifact (phase 1.8) for run/template tests.

        Deduped on ``(artifact_type, content_hash)`` so a test can call it more
        than once with the default hash without tripping the unique constraint.
        """
        from dopilot_server.models.execution import BuildArtifact
        from sqlalchemy import select

        existing = (
            await self.session.execute(
                select(BuildArtifact).where(
                    BuildArtifact.artifact_type == artifact_type,
                    BuildArtifact.content_hash == sha256,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        if artifact_type == "python_wheel":
            metadata = {
                "distribution": project,
                "version": f"sha256-{sha256[:12]}",
                "fetch_path": f"/api/v1/artifacts/python_wheel/{sha256}/wheel",
            }
            filename = f"{project}.whl"
        else:
            metadata = {
                "project": project,
                "version": f"sha256-{sha256[:12]}",
                "spiders": list(spiders),
                "fetch_path": f"/api/v1/artifacts/scrapy/{sha256}/egg",
            }
            filename = f"{project}.egg"

        artifact = BuildArtifact(
            id=uuid.uuid4().hex,
            artifact_type=artifact_type,
            package_format=package_format,
            name=project,
            filename=filename,
            content_hash=sha256,
            size_bytes=123,
            artifact_metadata=metadata,
        )
        self.session.add(artifact)
        await self.session.commit()
        return artifact

    async def running_task(self, node: Node | None = None):
        """Create a running task + one running execution + active log file.

        Returns ``(task, execution, log_file)`` — the parent run, its atomic
        per-node execution, and the log index row.
        """
        if node is None:
            node = await self.healthy_node()
        req = ExecutionRunRequest(
            artifact_type="scrapy",
            target="demo:phase1",
            node_strategy="all",
            params={"project": "demo", "spider": "phase1"},
        )
        task = svc.create_task(self.session, req)
        task.status = states.TASK_RUNNING
        execution = svc.create_execution(self.session, task, node)
        execution.status = states.EXEC_RUNNING
        execution.remote_job_id = "job-x"
        log_file = svc.create_log_file(
            self.session, self.settings, task, execution
        )
        await self.session.commit()
        return task, execution, log_file


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
    subs: SubscriptionManager,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Any,
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
    app.dependency_overrides[get_subscriptions] = lambda: subs
    # Phase 1.5: the run/cancel path dispatches over the Redis command stream.
    producer = CommandProducer(redis, RedisSettings())
    dispatcher = CommandDispatcher(sessionmaker, producer)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
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


@pytest.fixture
def exec_redis(fake_redis) -> Any:
    """A FakeRedisStreams shared by the exec client's dispatcher and the test."""
    return fake_redis()


@pytest_asyncio.fixture
async def exec_client(
    exec_settings: Settings,
    db_session: AsyncSession,
    subscriptions: SubscriptionManager,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    exec_redis: Any,
) -> AsyncIterator[AsyncClient]:
    """Auth-OFF client wired to the Redis command stream + a temp log root."""
    async with _build_exec_client(
        exec_settings, db_session, subscriptions,
        test_sessionmaker, exec_redis,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def exec_client_auth_on(
    exec_settings_auth_on: Settings,
    db_session: AsyncSession,
    subscriptions: SubscriptionManager,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    exec_redis: Any,
) -> AsyncIterator[AsyncClient]:
    """Auth-ON client wired to the Redis command stream + a temp log root."""
    async with _build_exec_client(
        exec_settings_auth_on,
        db_session,
        subscriptions,
        test_sessionmaker,
        exec_redis,
    ) as ac:
        yield ac


# --------------------------------------------------------------------------
# PostgreSQL-backed fixtures (log-flood guard concurrency tests)
# --------------------------------------------------------------------------
# ``FOR UPDATE`` row locks and the partial-unique-index upsert only behave for
# real under PostgreSQL (aiosqlite serialises everything). The plan requires the
# concurrency cases to produce PostgreSQL evidence, so these fixtures FAIL
# (never skip) when ``DOPILOT_TEST_DATABASE_URL`` is not set — start
# ``scripts/dev-db.sh up`` and export e.g.
# ``postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot``.
import os  # noqa: E402

PG_TEST_URL = os.environ.get("DOPILOT_TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    if not PG_TEST_URL:
        pytest.fail(
            "DOPILOT_TEST_DATABASE_URL is not set: PostgreSQL concurrency tests must run "
            "against scripts/dev-db.sh (they are not allowed to skip)"
        )
    engine = create_async_engine(PG_TEST_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        # Dispose FIRST: a test that failed mid-interleaving may leave a task
        # holding a row lock in a pooled connection; dropping the schema on a
        # fresh engine afterwards can then never deadlock on it.
        await engine.dispose()
        cleanup = create_async_engine(PG_TEST_URL)
        async with cleanup.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await cleanup.dispose()


@pytest.fixture
def pg_sessionmaker(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)
