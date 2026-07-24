"""Resource dashboard (D2/D3) tests: snapshot collection, level rules, scope
isolation, defensive agent parsing, the three admin endpoints, the sampler loop,
config, and — gated on a real PostgreSQL — the PG-only size/age SQL path."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from dopilot_protocol.streams import EVENT_STREAM, LOG_STREAM, command_stream
from dopilot_server import resource_stats
from dopilot_server.app import create_app
from dopilot_server.config.loader import get_settings
from dopilot_server.config.settings import Settings
from dopilot_server.db.engine import get_session
from dopilot_server.models.event_audit import EventAudit
from dopilot_server.models.execution import ExecutionLogFile, Task
from dopilot_server.models.node import Node
from dopilot_server.redis.client import RedisStreams
from dopilot_server.resource_stats import (
    ResourceStatsLoop,
    _entry,
    _level,
    collect_snapshot,
)
from dopilot_server.retention import RetentionSweepLoop
from dopilot_server.services import states
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import make_settings

API_TOKEN = "static-admin-api-token-0123456789"
NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _settings(tmp_path, *, auth_on: bool = False) -> Settings:
    s = make_settings(
        auth_on=auth_on,
        logs_root=str(tmp_path / "logs"),
        artifacts_root=str(tmp_path / "arts"),
    )
    os.makedirs(s.logs.root_dir, exist_ok=True)
    os.makedirs(s.artifacts.root_dir, exist_ok=True)
    if auth_on:
        s.auth.admin_api_token = API_TOKEN
    return s


class FakeRedis:
    """Minimal Redis double for the resource sampler + rewrite-aof."""

    def __init__(self) -> None:
        self.memory = {"used_memory": 1000, "maxmemory": 2000}
        self.persistence = {"aof_current_size": 500}
        self.streams: dict[str, dict[str, Any]] = {}
        self.fail = False
        self.fail_xtrim: set[str] = set()
        self.bgrewriteaof_calls = 0
        self.raise_bgrewriteaof = False

    async def info(self, section: str | None = None) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("redis down")
        if section == "memory":
            return dict(self.memory)
        if section == "persistence":
            return dict(self.persistence)
        return {**self.memory, **self.persistence}

    async def xinfo_stream(self, stream: str) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("redis down")
        return self.streams.get(stream, {"length": 0, "first-entry": None})

    async def xtrim(self, stream, *, minid=None, maxlen=None, approximate=True):
        if stream in self.fail_xtrim:
            raise RuntimeError("xtrim fail")
        return 3

    async def bgrewriteaof(self):
        if self.raise_bgrewriteaof:
            raise RuntimeError("aof fail")
        self.bgrewriteaof_calls += 1
        return b"OK"


def _client(
    settings: Settings,
    session: AsyncSession,
    *,
    snapshot: dict | None = None,
    has_loop: bool = False,
    redis: Any = None,
) -> AsyncClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    async def _sess() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _sess
    if snapshot is not None or has_loop:
        app.state.resource_stats = SimpleNamespace(snapshot=snapshot)
    if redis is not None:
        app.state.redis = redis
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


async def _seed_task(
    session: AsyncSession,
    *,
    status: str = states.TASK_COMPLETE,
    created_days: float = 40,
    finished_days: float | None = None,
) -> Task:
    created = NOW - timedelta(days=created_days)
    finished = None if finished_days is None else NOW - timedelta(days=finished_days)
    task = Task(
        id=uuid.uuid4().hex,
        artifact_type="scrapy",
        target="demo:phase1",
        node_strategy="all",
        status=status,
        params={},
        created_at=created,
        finished_at=finished,
    )
    session.add(task)
    await session.commit()
    return task


async def _seed_node(
    session: AsyncSession,
    *,
    agent_id: str,
    last_seen_age: float,
    redis_ok: bool = True,
    disk: dict | None = None,
    persisted_status: str = "healthy",
) -> Node:
    health: dict[str, Any] = {}
    if redis_ok:
        health["redis"] = {
            "connected": True,
            "command_consumer": {"running": True},
        }
    if disk is not None:
        health["disk"] = disk
    node = Node(
        id=uuid.uuid4(),
        agent_id=agent_id,
        endpoint=f"agent://{agent_id}",
        status=persisted_status,
        capabilities={"scrapy": True},
        health=health,
        last_seen_at=NOW - timedelta(seconds=last_seen_age),
    )
    session.add(node)
    await session.commit()
    return node


def _fresh_disk(**over) -> dict:
    base = {
        "sampled_at": NOW.isoformat(),
        "interval_seconds": 600,
        "workspaces": {"count": 2, "bytes": 4096},
        "cache": {"bytes": 8192, "limit": 2147483648},
        "scrapyd": {"bytes": 1024},
        "outbox": {"files": 3, "bytes": 512, "limit": 100000},
        "state": {"executions": 5, "logpos": 5},
        "volume": {"total": 1000, "used": 500, "free": 500},
    }
    base.update(over)
    return base


def _scope_by(snapshot: dict, name: str) -> dict | None:
    return next((s for s in snapshot["scopes"] if s["scope"] == name), None)


# ---------------------------------------------------------------------------
# TC-02: level rules (occupancy + age, mutually exclusive segments)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [(69, "ok"), (70, "warn"), (89, "warn"), (90, "critical"), (100, "critical")],
)
def test_tc02_occupancy_levels(value, expected):
    assert _level("bytes", value, 100, 0) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(150, "ok"), (151, "warn"), (200, "warn"), (201, "critical")],
)
def test_tc02_age_levels_grace_lt_limit(value, expected):
    # limit=100, grace=50 -> critical_at = max(200, 150) = 200.
    assert _level("age", value, 100, 50) == expected


@pytest.mark.parametrize(
    "value,expected", [(300, "ok"), (301, "critical")]
)
def test_tc02_age_levels_grace_gt_limit(value, expected):
    # limit=100, grace=200 -> critical_at = max(200, 300) = 300 (no overlap).
    assert _level("age", value, 100, 200) == expected


def test_tc02_null_limit_is_ok_and_null_value_is_unknown():
    assert _entry("k", "bytes", 999, None)["level"] == "ok"
    assert _entry("k", "bytes", None, 100)["level"] == "unknown"
    assert _entry("k", "age", 999999, None)["level"] == "ok"


# ---------------------------------------------------------------------------
# TC-01: collect_snapshot on SQLite (server/postgres/agent shapes)
# ---------------------------------------------------------------------------


async def test_tc01_snapshot_shape_and_configured_roots(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    # Files under the CONFIGURED roots (distinct from server.data_dir=/server-data).
    (tmp_path / "logs" / "sub").mkdir(parents=True)
    (tmp_path / "logs" / "sub" / "a.log").write_bytes(b"x" * 100)
    (tmp_path / "arts" / "b.egg").write_bytes(b"y" * 200)
    await _seed_task(db_session)
    db_session.add(
        ExecutionLogFile(
            task_id=uuid.uuid4().hex,
            execution_id=uuid.uuid4().hex,
            storage_path="/x",
            size_bytes=12345,
        )
    )
    await db_session.commit()

    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)

    server = _scope_by(snap, "server")
    assert server["status"] == "ok"
    logs = next(e for e in server["entries"] if e["key"] == "server.logs_bytes")
    arts = next(
        e for e in server["entries"] if e["key"] == "server.artifacts_bytes"
    )
    assert logs["value"] == 100  # from logs.root_dir, NOT data_dir
    assert arts["value"] == 200
    max_lf = next(
        e for e in server["entries"] if e["key"] == "server.max_log_file_bytes"
    )
    assert max_lf["value"] == 12345

    pg = _scope_by(snap, "postgres")
    rows = next(e for e in pg["entries"] if e["key"] == "postgres.tasks_rows")
    assert rows["value"] == 1 and rows["kind"] == "count"
    # PG-only byte sizes are null (unknown) on SQLite.
    assert not any(e["key"] == "postgres.tasks_bytes" for e in pg["entries"])
    # redis is unavailable when no client is wired.
    assert _scope_by(snap, "redis")["status"] == "unavailable"


# ---------------------------------------------------------------------------
# TC-02 (data): effective-time predicate + closed-knob semantics
# ---------------------------------------------------------------------------


async def test_tc02_effective_time_predicate_not_false_red(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    settings.logs.retention_days = 30
    settings.maintenance.event_audit_retention_days = 30
    # Old created_at but RECENT finished_at -> age measured from finished_at.
    await _seed_task(db_session, created_days=400, finished_days=1)
    db_session.add(
        EventAudit(
            id=uuid.uuid4().hex,
            stream="s",
            redis_msg_id="1-0",
            execution_id=uuid.uuid4().hex,
            event_type="status",
            outcome="applied",
            processed_at=NOW - timedelta(days=1),
        )
    )
    await db_session.commit()

    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)
    pg = _scope_by(snap, "postgres")
    task_age = next(
        e for e in pg["entries"] if e["key"] == "postgres.oldest_terminal_task_age"
    )
    audit_age = next(
        e for e in pg["entries"] if e["key"] == "postgres.oldest_event_audit_age"
    )
    # ~1 day, well under the 30-day window -> ok, not a false red.
    assert task_age["value"] < 2 * 86400 and task_age["level"] == "ok"
    assert audit_age["value"] < 2 * 86400 and audit_age["level"] == "ok"


async def test_tc02_zero_retention_is_uncapped_ok(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    settings.logs.retention_days = 0
    settings.maintenance.event_audit_retention_days = 0
    settings.maintenance.enabled = False
    await _seed_task(db_session, created_days=999, finished_days=999)
    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)
    assert snap["sweep_enabled"] is False
    pg = _scope_by(snap, "postgres")
    task_age = next(
        e for e in pg["entries"] if e["key"] == "postgres.oldest_terminal_task_age"
    )
    assert task_age["limit"] is None and task_age["level"] == "ok"


# ---------------------------------------------------------------------------
# TC-03: redis scope — normal, empty streams, whole-scope + single-metric fail,
# and PG-scope isolation
# ---------------------------------------------------------------------------


async def test_tc03_redis_scope_normal_and_command_stream_no_age(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    redis = FakeRedis()
    old_ms = int((NOW - timedelta(seconds=100000)).timestamp() * 1000)
    redis.streams[LOG_STREAM] = {"length": 5, "first-entry": (f"{old_ms}-0", [])}
    redis.streams[EVENT_STREAM] = {"length": 2, "first-entry": (f"{old_ms}-0", [])}
    await _seed_node(
        db_session, agent_id="a1", last_seen_age=1, disk=_fresh_disk()
    )
    redis.streams[command_stream("a1")] = {"length": 9, "first-entry": None}

    snap = await collect_snapshot(test_sessionmaker, settings, redis, now=NOW)
    rd = _scope_by(snap, "redis")
    assert rd["status"] == "ok"
    mem = next(e for e in rd["entries"] if e["key"] == "redis.used_memory")
    assert mem["value"] == 1000 and mem["limit"] == 2000 and mem["level"] == "ok"
    assert any(e["key"] == "redis.aof_bytes" for e in rd["entries"])
    assert any(e["key"] == "redis.stream_len:logs" for e in rd["entries"])
    assert any(e["key"] == "redis.stream_age:logs" for e in rd["entries"])
    # command stream: length only, NEVER an age metric.
    assert any(e["key"] == "redis.command_stream_len:a1" for e in rd["entries"])
    assert not any("command_stream_age" in e["key"] for e in rd["entries"])


async def test_tc03_empty_streams_scope_ok(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    redis = FakeRedis()  # all streams default to length 0 / no first-entry
    await _seed_node(
        db_session, agent_id="a1", last_seen_age=1, disk=_fresh_disk()
    )
    snap = await collect_snapshot(test_sessionmaker, settings, redis, now=NOW)
    rd = _scope_by(snap, "redis")
    assert rd["status"] == "ok"
    length = next(e for e in rd["entries"] if e["key"] == "redis.stream_len:logs")
    assert length["value"] == 0
    # No first entry -> no age metric emitted (not an unknown-noise row).
    assert not any(e["key"] == "redis.stream_age:logs" for e in rd["entries"])


async def test_tc03_client_maps_no_such_key():
    class _Inner:
        async def xinfo_stream(self, stream):
            raise ResponseError("ERR no such key")

    empty = await RedisStreams(_Inner()).xinfo_stream("missing")
    assert empty == {"length": 0, "first-entry": None}

    class _Boom:
        async def xinfo_stream(self, stream):
            raise ResponseError("WRONGTYPE not a stream")

    with pytest.raises(ResponseError):
        await RedisStreams(_Boom()).xinfo_stream("x")


async def test_tc03_redis_whole_scope_unavailable_others_ok(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    redis = FakeRedis()
    redis.fail = True
    snap = await collect_snapshot(test_sessionmaker, settings, redis, now=NOW)
    assert _scope_by(snap, "redis")["status"] == "unavailable"
    assert _scope_by(snap, "redis")["entries"] == []
    assert _scope_by(snap, "server")["status"] == "ok"
    assert _scope_by(snap, "postgres")["status"] == "ok"


async def test_tc03_aof_missing_is_unknown(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    redis = FakeRedis()
    redis.persistence = {}  # AOF off -> aof_current_size missing
    snap = await collect_snapshot(test_sessionmaker, settings, redis, now=NOW)
    aof = next(
        e for e in _scope_by(snap, "redis")["entries"]
        if e["key"] == "redis.aof_bytes"
    )
    assert aof["value"] is None and aof["level"] == "unknown"


def test_tc03_du_missing_dir_is_zero(tmp_path):
    # A not-yet-created root is legitimately 0 bytes, NOT an access failure.
    assert resource_stats._du(str(tmp_path / "never")) == 0


def test_tc03_du_access_failure_is_unknown(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    d.mkdir()

    def _walk(path, onerror=None):
        if onerror:
            onerror(PermissionError("permission denied"))
        return iter([])

    monkeypatch.setattr(resource_stats.os, "walk", _walk)
    # Existing but unreadable dir -> None (rendered as unknown), never a fake 0.
    # PermissionError must NOT be masked into a false "absent"/0 (review R-02:
    # _du no longer gates on os.path.exists()).
    assert resource_stats._du(str(d)) is None


def test_tc03_du_vanished_file_mid_walk_is_benign(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    d.mkdir()
    (d / "a.log").write_bytes(b"x" * 10)

    real_stat = resource_stats.os.stat

    def _stat(path, *a, **k):
        if str(path).endswith("a.log"):
            raise FileNotFoundError  # vanished between walk and stat
        return real_stat(path, *a, **k)

    monkeypatch.setattr(resource_stats.os, "stat", _stat)
    # A vanished file is skipped (benign), not an access failure.
    assert resource_stats._du(str(d)) == 0


async def test_tc03_server_scope_du_failure_is_unknown_not_zero(
    tmp_path, db_session, test_sessionmaker, monkeypatch
):
    settings = _settings(tmp_path)

    def _du_fail(path):
        return None if "logs" in path else 0

    monkeypatch.setattr(resource_stats, "_du", _du_fail)
    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)
    server = _scope_by(snap, "server")
    assert server["status"] == "ok"  # one bad dir does not fail the whole scope
    logs = next(e for e in server["entries"] if e["key"] == "server.logs_bytes")
    assert logs["value"] is None and logs["level"] == "unknown"


async def test_tc03_nodes_read_failure_surfaces_agents_unavailable(
    tmp_path, test_sessionmaker, monkeypatch
):
    settings = _settings(tmp_path)

    async def _boom_read(*a, **k):
        return [], False  # DB read failed

    monkeypatch.setattr(resource_stats, "_read_nodes", _boom_read)
    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)
    agents = _scope_by(snap, "agents")
    assert agents is not None and agents["status"] == "unavailable"
    # server/postgres still collected.
    assert _scope_by(snap, "server")["status"] == "ok"


async def test_tc03_read_nodes_returns_ok_flag(tmp_path):
    settings = _settings(tmp_path)

    class _BoomSession:
        async def execute(self, *a, **k):
            raise RuntimeError("db down")

        async def rollback(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def _maker():
        return _BoomSession()

    nodes, ok = await resource_stats._read_nodes(_maker, settings, NOW)
    assert nodes == [] and ok is False


async def test_tc03_postgres_failure_isolated(
    tmp_path, db_session, test_sessionmaker, monkeypatch
):
    settings = _settings(tmp_path)
    redis = FakeRedis()
    await _seed_node(
        db_session, agent_id="a1", last_seen_age=1, disk=_fresh_disk()
    )

    async def _boom(*a, **k):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(resource_stats, "_collect_postgres", _boom)
    snap = await collect_snapshot(test_sessionmaker, settings, redis, now=NOW)
    assert _scope_by(snap, "postgres")["status"] == "unavailable"
    assert _scope_by(snap, "server")["status"] == "ok"
    assert _scope_by(snap, "redis")["status"] == "ok"
    assert _scope_by(snap, "agent:a1")["status"] == "ok"


# ---------------------------------------------------------------------------
# TC-04: endpoint auth + agent scope status (dynamic) + defensive parsing
# ---------------------------------------------------------------------------


async def test_tc04_agent_scope_statuses(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    await _seed_node(db_session, agent_id="a-ok", last_seen_age=1, disk=_fresh_disk())
    await _seed_node(
        db_session, agent_id="a-degraded", last_seen_age=1,
        redis_ok=False, disk=_fresh_disk(),
    )
    await _seed_node(
        db_session, agent_id="a-stale", last_seen_age=1,
        disk=_fresh_disk(sampled_at=(NOW - timedelta(seconds=2000)).isoformat()),
    )
    await _seed_node(
        db_session, agent_id="a-unhealthy", last_seen_age=9999, disk=_fresh_disk()
    )
    await _seed_node(db_session, agent_id="a-nodisk", last_seen_age=1, disk=None)
    # Persisted status healthy but heartbeat long gone -> dynamic unhealthy.
    await _seed_node(
        db_session, agent_id="a-disc", last_seen_age=9999,
        persisted_status="healthy", disk=_fresh_disk(),
    )

    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)
    assert _scope_by(snap, "agent:a-ok")["status"] == "ok"
    assert _scope_by(snap, "agent:a-degraded")["status"] == "ok"
    assert _scope_by(snap, "agent:a-stale")["status"] == "stale"
    assert _scope_by(snap, "agent:a-unhealthy")["status"] == "unavailable"
    assert _scope_by(snap, "agent:a-nodisk")["status"] == "unavailable"
    disc = _scope_by(snap, "agent:a-disc")
    assert disc["status"] == "unavailable" and disc["last_seen_at"] is not None
    # A cache entry's level derives from the agent-reported limit.
    ok_entries = _scope_by(snap, "agent:a-ok")["entries"]
    assert any(e["key"] == "agent.cache_bytes" for e in ok_entries)


async def test_tc04_malformed_disk_samples_isolated(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    await _seed_node(db_session, agent_id="a-good", last_seen_age=1, disk=_fresh_disk())
    await _seed_node(
        db_session, agent_id="a-baddate", last_seen_age=1,
        disk=_fresh_disk(sampled_at="not-a-date"),
    )
    await _seed_node(
        db_session, agent_id="a-badinterval", last_seen_age=1,
        disk=_fresh_disk(interval_seconds=0),
    )
    await _seed_node(
        db_session, agent_id="a-negint", last_seen_age=1,
        disk=_fresh_disk(interval_seconds=-5),
    )
    await _seed_node(
        db_session, agent_id="a-badfield", last_seen_age=1,
        disk=_fresh_disk(workspaces={"bytes": "big", "count": -1}),
    )

    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)
    assert _scope_by(snap, "agent:a-good")["status"] == "ok"
    assert _scope_by(snap, "agent:a-baddate")["status"] == "unavailable"
    assert _scope_by(snap, "agent:a-badinterval")["status"] == "unavailable"
    assert _scope_by(snap, "agent:a-negint")["status"] == "unavailable"
    # Field-level garbage: scope still ok, the bad workspace entries just omitted.
    bad = _scope_by(snap, "agent:a-badfield")
    assert bad["status"] == "ok"
    assert not any(e["key"] == "agent.workspaces_bytes" for e in bad["entries"])


async def test_tc04_endpoint_auth_and_serialization(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path, auth_on=True)
    await _seed_node(db_session, agent_id="a1", last_seen_age=1, disk=_fresh_disk())
    snap = await collect_snapshot(test_sessionmaker, settings, None, now=NOW)

    async with _client(settings, db_session, snapshot=snap) as ac:
        assert (await ac.get("/api/v1/maintenance/resource-stats")).status_code == 401
        resp = await ac.get(
            "/api/v1/maintenance/resource-stats", headers=_auth()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sampled_at"] is not None
        assert any(s["scope"] == "agent:a1" for s in body["scopes"])


async def test_tc04_no_snapshot_zero_sampling(
    tmp_path, db_session, monkeypatch
):
    settings = _settings(tmp_path)
    calls = {"n": 0}

    async def _counted(*a, **k):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(resource_stats, "collect_snapshot", _counted)
    # No app.state.resource_stats -> endpoint must return empty, sample nothing.
    async with _client(settings, db_session) as ac:
        resp = await ac.get("/api/v1/maintenance/resource-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sampled_at"] is None and body["scopes"] == []
    assert calls["n"] == 0  # request path NEVER samples


async def test_tc04_no_snapshot_reports_true_sweep_enabled(tmp_path, db_session):
    # Disabled auto-sweep + disabled sampler must NOT be mislabelled as on.
    settings = _settings(tmp_path)
    settings.maintenance.enabled = False
    async with _client(settings, db_session) as ac:  # no cached snapshot
        resp = await ac.get("/api/v1/maintenance/resource-stats")
    body = resp.json()
    assert resp.status_code == 200
    assert body["sampled_at"] is None
    assert body["sweep_enabled"] is False


# ---------------------------------------------------------------------------
# TC-05: sweep-now — success, step isolation, redis/retention short-circuits
# ---------------------------------------------------------------------------


async def _seed_expired(session: AsyncSession) -> None:
    await _seed_task(session, finished_days=40)
    session.add(
        EventAudit(
            id=uuid.uuid4().hex,
            stream="s",
            redis_msg_id=f"{uuid.uuid4().hex}",
            execution_id=uuid.uuid4().hex,
            event_type="status",
            outcome="applied",
            processed_at=NOW - timedelta(days=99),
        )
    )
    await session.commit()


async def test_tc05_sweep_now_auth(tmp_path, db_session):
    settings = _settings(tmp_path, auth_on=True)
    async with _client(settings, db_session) as ac:
        assert (await ac.post("/api/v1/maintenance/sweep-now")).status_code == 401


async def test_tc05_sweep_now_all_ok(tmp_path, db_session):
    settings = _settings(tmp_path)
    settings.redis.log_retention_seconds = 3600
    await _seed_expired(db_session)
    redis = FakeRedis()
    async with _client(settings, db_session, redis=redis) as ac:
        resp = await ac.post("/api/v1/maintenance/sweep-now")
    assert resp.status_code == 200
    steps = resp.json()["steps"]
    assert steps["cleanup"]["status"] == "ok"
    assert steps["event_audit"]["status"] == "ok"
    assert steps["event_audit"]["pruned"] >= 1
    assert steps["stream_trim"]["status"] == "ok"


async def test_tc05_sweep_now_cleanup_fails_others_run(
    tmp_path, db_session, monkeypatch
):
    settings = _settings(tmp_path)
    settings.redis.log_retention_seconds = 3600
    await _seed_expired(db_session)

    from dopilot_server.services import maintenance as m

    async def _boom(*a, **k):
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(m, "cleanup_terminal_data", _boom)
    redis = FakeRedis()
    async with _client(settings, db_session, redis=redis) as ac:
        resp = await ac.post("/api/v1/maintenance/sweep-now")
    steps = resp.json()["steps"]
    assert steps["cleanup"]["status"] == "failed"
    assert steps["event_audit"]["status"] == "ok"  # still ran
    assert steps["stream_trim"]["status"] == "ok"


async def test_tc05_sweep_now_prune_fails_others_run(
    tmp_path, db_session, monkeypatch
):
    settings = _settings(tmp_path)
    settings.redis.log_retention_seconds = 3600
    await _seed_expired(db_session)

    from dopilot_server.services import maintenance as m

    async def _boom(*a, **k):
        raise RuntimeError("prune boom")

    monkeypatch.setattr(m, "prune_event_audit", _boom)
    redis = FakeRedis()
    async with _client(settings, db_session, redis=redis) as ac:
        resp = await ac.post("/api/v1/maintenance/sweep-now")
    assert resp.status_code == 200
    steps = resp.json()["steps"]
    assert steps["cleanup"]["status"] == "ok"
    assert steps["event_audit"]["status"] == "failed"
    assert steps["stream_trim"]["status"] == "ok"  # still ran after prune failure


async def test_tc05_sweep_now_single_stream_trim_failure(
    tmp_path, db_session
):
    settings = _settings(tmp_path)
    settings.redis.log_retention_seconds = 3600
    await _seed_expired(db_session)
    redis = FakeRedis()
    redis.fail_xtrim = {EVENT_STREAM}  # one stream fails, the other succeeds
    async with _client(settings, db_session, redis=redis) as ac:
        resp = await ac.post("/api/v1/maintenance/sweep-now")
    trim = resp.json()["steps"]["stream_trim"]
    assert trim["status"] == "failed"
    assert "trimmed" in trim["streams"][LOG_STREAM]
    assert "error" in trim["streams"][EVENT_STREAM]


async def test_tc05_sweep_now_no_redis_skips_trim(tmp_path, db_session):
    settings = _settings(tmp_path)
    settings.redis.log_retention_seconds = 3600
    await _seed_expired(db_session)
    async with _client(settings, db_session) as ac:  # no redis on app.state
        resp = await ac.post("/api/v1/maintenance/sweep-now")
    assert resp.json()["steps"]["stream_trim"]["status"] == "skipped"


async def test_tc05_sweep_now_retention_zero_skips_cleanup(tmp_path, db_session):
    settings = _settings(tmp_path)
    settings.logs.retention_days = 0
    await _seed_task(db_session, finished_days=40)
    async with _client(settings, db_session) as ac:
        resp = await ac.post("/api/v1/maintenance/sweep-now")
    assert resp.json()["steps"]["cleanup"]["status"] == "skipped"
    # No terminal data deleted.
    from sqlalchemy import func, select

    count = (
        await db_session.execute(select(func.count()).select_from(Task))
    ).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# TC-06: rewrite-aof
# ---------------------------------------------------------------------------


async def test_tc06_rewrite_aof(tmp_path, db_session):
    settings = _settings(tmp_path, auth_on=True)
    redis = FakeRedis()
    async with _client(settings, db_session, redis=redis) as ac:
        assert (
            await ac.post("/api/v1/maintenance/redis-rewrite-aof")
        ).status_code == 401
        resp = await ac.post(
            "/api/v1/maintenance/redis-rewrite-aof", headers=_auth()
        )
    assert resp.status_code == 200 and resp.json()["started"] is True
    assert redis.bgrewriteaof_calls == 1


async def test_tc06_rewrite_aof_no_redis_503(tmp_path, db_session):
    settings = _settings(tmp_path)
    async with _client(settings, db_session) as ac:  # no redis
        resp = await ac.post("/api/v1/maintenance/redis-rewrite-aof")
    assert resp.status_code == 503
    assert resp.json()["code"] == "maintenance.redis_unavailable"


async def test_tc06_rewrite_aof_call_raises_503(tmp_path, db_session):
    settings = _settings(tmp_path)
    redis = FakeRedis()
    redis.raise_bgrewriteaof = True
    async with _client(settings, db_session, redis=redis) as ac:
        resp = await ac.post("/api/v1/maintenance/redis-rewrite-aof")
    assert resp.status_code == 503
    assert resp.json()["code"] == "maintenance.redis_unavailable"


# ---------------------------------------------------------------------------
# TC-07: sampler loop resilience + retention 0 short-circuit
# ---------------------------------------------------------------------------


async def test_tc07_loop_samples_and_recovers(
    tmp_path, test_sessionmaker, monkeypatch
):
    settings = _settings(tmp_path)
    calls = {"n": 0}

    async def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"sampled_at": "x", "sweep_enabled": True, "scopes": []}

    monkeypatch.setattr(resource_stats, "collect_snapshot", _flaky)
    loop = ResourceStatsLoop(
        test_sessionmaker, settings, None, interval_seconds=0.01
    )
    loop.start()
    for _ in range(200):
        if calls["n"] >= 2:
            break
        await asyncio.sleep(0.01)
    await loop.stop()
    assert calls["n"] >= 2  # survived the first exception
    assert loop.snapshot is not None  # recovered on a later tick


async def test_tc07_retention_zero_sweep_skips_cleanup(
    tmp_path, db_session, test_sessionmaker
):
    settings = _settings(tmp_path)
    settings.logs.retention_days = 0
    await _seed_task(db_session, finished_days=40)
    loop = RetentionSweepLoop(test_sessionmaker, settings, None)
    await loop.sweep_once(now=NOW)  # must NOT delete terminal data
    from sqlalchemy import func, select

    count = (
        await db_session.execute(select(func.count()).select_from(Task))
    ).scalar()
    assert count == 1


async def test_tc07_lifespan_gates_stats_loop(monkeypatch):
    """The real lifespan starts a ResourceStatsLoop only when the interval > 0.
    With the sampler off, no loop is constructed and app.state.resource_stats is
    None (the endpoint then serves an empty snapshot without sampling — see
    test_tc04_no_snapshot_zero_sampling)."""
    from dopilot_server import app as appmod

    constructed = {"stats": 0}

    class _FakeWorker:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        async def stop(self):
            pass

    class _FakeStats(_FakeWorker):
        snapshot = None

        def __init__(self, *a, **k):
            constructed["stats"] += 1

    class _FakeRedis:
        async def aclose(self):
            pass

    async def _noop_seed(*a, **k):
        pass

    monkeypatch.setattr(appmod, "seed_builtin_artifacts", _noop_seed)
    monkeypatch.setattr(appmod, "build_redis", lambda url: _FakeRedis())
    monkeypatch.setattr(appmod, "CommandProducer", lambda *a, **k: object())
    monkeypatch.setattr(appmod, "CommandDispatcher", lambda *a, **k: _FakeWorker())
    monkeypatch.setattr(appmod, "EventConsumer", lambda *a, **k: _FakeWorker())
    monkeypatch.setattr(appmod, "LogConsumer", lambda *a, **k: _FakeWorker())
    monkeypatch.setattr(appmod, "RedisReconcileLoop", lambda *a, **k: _FakeWorker())
    monkeypatch.setattr(appmod, "RetentionSweepLoop", lambda *a, **k: _FakeWorker())
    monkeypatch.setattr(appmod, "ResourceStatsLoop", _FakeStats)
    monkeypatch.setattr(appmod, "build_schedule_runner", lambda *a, **k: None)

    off = make_settings()
    off.maintenance.stats_interval_seconds = 0
    app_off = appmod.create_app(off)
    async with app_off.router.lifespan_context(app_off):
        assert getattr(app_off.state, "resource_stats", None) is None
    assert constructed["stats"] == 0

    on = make_settings()
    on.maintenance.stats_interval_seconds = 60
    app_on = appmod.create_app(on)
    async with app_on.router.lifespan_context(app_on):
        assert app_on.state.resource_stats is not None
    assert constructed["stats"] == 1


# ---------------------------------------------------------------------------
# TC-08: config (default + env override)
# ---------------------------------------------------------------------------


def test_tc08_stats_interval_default():
    assert make_settings().maintenance.stats_interval_seconds == 60


def test_tc08_stats_interval_toml(tmp_path):
    cfg = tmp_path / "server.toml"
    cfg.write_text(
        '[auth]\nadmin_username="a"\nadmin_password="b"\n'
        'token_secret="c"\n[database]\nurl="sqlite+aiosqlite:///:memory:"\n'
        "[maintenance]\nstats_interval_seconds=17\n"
    )
    from dopilot_server.config.loader import load_settings

    s = load_settings(str(cfg))
    assert s.maintenance.stats_interval_seconds == 17


def test_tc08_stats_interval_env_override(tmp_path, monkeypatch):
    cfg = tmp_path / "server.toml"
    cfg.write_text(
        '[auth]\nadmin_username="a"\nadmin_password="b"\n'
        'token_secret="c"\n[database]\nurl="sqlite+aiosqlite:///:memory:"\n'
        "[maintenance]\nstats_interval_seconds=17\n"  # env must WIN over this
    )
    monkeypatch.setenv("DOPILOT_MAINTENANCE_STATS_INTERVAL_SECONDS", "5")
    from dopilot_server.config.loader import load_settings

    s = load_settings(str(cfg))
    assert s.maintenance.stats_interval_seconds == 5


# ---------------------------------------------------------------------------
# TC-11: heartbeat disk -> nodes.health -> resource-stats (end to end)
# ---------------------------------------------------------------------------


async def test_tc11_heartbeat_disk_flows_to_stats(
    tmp_path, db_session, test_sessionmaker
):
    from dopilot_protocol import AgentHeartbeatRequest, CapabilitySet
    from dopilot_server.nodes.service import upsert_node_heartbeat
    from sqlalchemy import select

    settings = _settings(tmp_path)
    # upsert stamps last_seen_at with real now, so align the sample + collect now.
    now = datetime.now(UTC)
    hb = AgentHeartbeatRequest(
        agent_id="a1",
        version="1.0",
        capabilities=CapabilitySet(scrapy=True),
        load={"running_attempts": 0},
        detail={
            "redis": {"connected": True, "command_consumer": {"running": True}},
            "disk": _fresh_disk(sampled_at=now.isoformat()),
        },
        endpoint=None,
        reported_at=now.isoformat(),
    )
    await upsert_node_heartbeat(db_session, "a1", hb)
    await db_session.commit()

    # nodes.health carries disk verbatim.
    node = (
        await db_session.execute(select(Node).where(Node.agent_id == "a1"))
    ).scalar_one()
    assert node.health["disk"]["workspaces"]["bytes"] == 4096

    snap = await collect_snapshot(test_sessionmaker, settings, None, now=now)
    agent = _scope_by(snap, "agent:a1")
    assert agent is not None and agent["status"] == "ok"
    assert any(e["key"] == "agent.workspaces_bytes" for e in agent["entries"])


# ---------------------------------------------------------------------------
# TC-17: real PostgreSQL size/age SQL path (gated on DOPILOT_TEST_PG_URL)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pg_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("DOPILOT_TEST_PG_URL")
    if not url:
        pytest.skip("DOPILOT_TEST_PG_URL not set (real PostgreSQL not available)")
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def test_tc17_postgres_size_and_age_real(tmp_path, pg_sessionmaker):
    settings = _settings(tmp_path)
    async with pg_sessionmaker() as s:
        await _seed_task(s, finished_days=40)
    snap = await collect_snapshot(pg_sessionmaker, settings, None, now=NOW)
    pg = _scope_by(snap, "postgres")
    assert pg["status"] == "ok"
    # PG-only relation size present and a valid non-negative int.
    tasks_bytes = next(
        e for e in pg["entries"] if e["key"] == "postgres.tasks_bytes"
    )
    assert isinstance(tasks_bytes["value"], int) and tasks_bytes["value"] >= 0
    db_bytes = next(
        e for e in pg["entries"] if e["key"] == "postgres.database_bytes"
    )
    assert isinstance(db_bytes["value"], int) and db_bytes["value"] > 0
    rows = next(e for e in pg["entries"] if e["key"] == "postgres.tasks_rows")
    assert rows["value"] >= 1
