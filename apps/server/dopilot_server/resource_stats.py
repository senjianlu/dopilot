"""Resource-usage sampler for the /maintenance dashboard (D2).

A single always-on background loop (:class:`ResourceStatsLoop`) — a sibling of
:class:`~dopilot_server.retention.RetentionSweepLoop` — periodically snapshots
server disk / PostgreSQL / Redis / per-agent usage and caches it in memory. The
``GET /maintenance/resource-stats`` endpoint serves ONLY that cached snapshot and
never samples on the request path (expensive directory walks and ``INFO`` calls
would otherwise run per request; hard architecture constraint).

The snapshot is a two-layer contract:

- **scope** (``server`` / ``postgres`` / ``redis`` / ``agent:<id>``) carries a
  ``status`` of ``ok | stale | unavailable``. A collection failure degrades ONLY
  that scope (each DB-backed scope opens its OWN session so one aborted
  transaction can never cascade); the rest still return.
- **entry** carries ``{key, kind, value, limit, level}`` where ``kind`` is
  ``bytes | count | age`` and ``level`` is ``ok | warn | critical | unknown``.
  ``value=None`` (AOF off, a PG-only size on SQLite, an empty table's oldest-row
  age) is ``unknown``; ``limit=None`` (an explicitly-disabled cap) is always
  ``ok``.

Agent disk metrics come from the free-form ``nodes.health["disk"]`` that agents
attach to their heartbeats. Because that dict is untrusted (old versions, hand
edits, malformed samples), it is parsed defensively per field and a bad sample
degrades only its own agent scope.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
from datetime import UTC, datetime
from typing import Any

from dopilot_protocol.streams import EVENT_STREAM, LOG_STREAM, command_stream
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config.settings import Settings
from .models.command_outbox import CommandOutbox
from .models.event_audit import EventAudit
from .models.execution import Execution, ExecutionLogFile, Task
from .models.node import Node
from .nodes.service import _aggregate_node_status
from .redis.client import RedisStreamClient
from .services import states

logger = logging.getLogger(__name__)

# PostgreSQL relation-size table whitelist (name -> model). Names are constants,
# never external input, so binding them into ``to_regclass(:n)`` is safe.
_PG_TABLES: dict[str, type] = {
    "tasks": Task,
    "executions": Execution,
    "execution_log_files": ExecutionLogFile,
    "command_outbox": CommandOutbox,
    "event_audit": EventAudit,
}

# WARN at >=70% of a cap, CRITICAL at >=90% (occupancy metrics).
_WARN_RATIO = 0.70
_CRITICAL_RATIO = 0.90


# --- value helpers ---------------------------------------------------------


def _num(value: Any) -> int | None:
    """A finite, non-negative int/float (NOT bool, NOT str) -> int, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value >= 0 else None
    return None


def _limit(value: Any) -> int | None:
    """A positive cap -> int; 0 / negative / invalid -> None (cap disabled)."""
    n = _num(value)
    return n if n and n > 0 else None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into an aware datetime, or None on any garbage."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _age_seconds(dt: Any, now: datetime) -> int | None:
    if isinstance(dt, datetime):
        aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        return max(0, int((now - aware).total_seconds()))
    return None


def _level(kind: str, value: int | None, limit: int | None, grace: int) -> str:
    if value is None:
        return "unknown"
    if limit is None:
        return "ok"
    if kind == "age":
        # Age metrics sit near their retention window in steady state, so the
        # occupancy ratios do not apply. Segments are mutually exclusive and
        # ordered (critical wins) so a legal ``grace > limit`` config never
        # produces an overlapping ok/critical verdict.
        critical_at = max(2 * limit, limit + grace)
        if value > critical_at:
            return "critical"
        if value > limit + grace:
            return "warn"
        return "ok"
    if limit <= 0:
        return "ok"
    ratio = value / limit
    if ratio >= _CRITICAL_RATIO:
        return "critical"
    if ratio >= _WARN_RATIO:
        return "warn"
    return "ok"


def _entry(
    key: str,
    kind: str,
    value: int | None,
    limit: int | None,
    *,
    grace: int = 0,
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "value": value,
        "limit": limit,
        "level": _level(kind, value, limit, grace),
    }


def _scope(
    name: str,
    status: str,
    sampled_at: str | None,
    last_seen_at: str | None,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scope": name,
        "status": status,
        "sampled_at": sampled_at,
        "last_seen_at": last_seen_at,
        "entries": entries,
    }


def _unavailable(name: str, now: datetime) -> dict[str, Any]:
    return _scope(name, "unavailable", None, None, [])


# --- filesystem helpers (offloaded to a thread) ----------------------------


def _raise(exc: OSError) -> None:
    raise exc


def _du(path: str) -> int | None:
    """Total byte size under ``path``.

    Distinguishes a genuinely-absent directory (``0`` — a fresh deploy that has
    not written logs/artifacts yet is legitimately zero) from an ACCESS FAILURE
    (``None`` — a permission error or unreadable entry). The caller renders
    ``None`` as an ``unknown`` metric rather than a misleading ``0``, so a
    misconfigured/unreadable root is never reported as "no usage".

    ONLY ``FileNotFoundError`` counts as "absent" — ``os.path.exists()`` is
    deliberately avoided because it swallows ``PermissionError`` into a false
    "absent" (review R-02). A file vanishing mid-walk is benign and skipped."""
    total = 0
    try:
        for dirpath, _dirs, filenames in os.walk(path, onerror=_raise):
            for name in filenames:
                try:
                    total += os.stat(os.path.join(dirpath, name)).st_size
                except FileNotFoundError:
                    continue  # vanished mid-walk — benign
    except FileNotFoundError:
        return 0  # top dir not created yet — legit empty
    except OSError:
        return None  # permission / access failure -> unknown, never a fake 0
    return total


def _distinct_volumes(paths: list[str]) -> list[str]:
    """De-duplicate paths that live on the same device (st_dev); skip missing."""
    seen: dict[int, str] = {}
    for path in paths:
        try:
            dev = os.stat(path).st_dev
        except OSError:
            continue
        seen.setdefault(dev, path)
    return list(seen.values())


def _disk_usage(path: str) -> tuple[int, int, int] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.total, usage.used, usage.free


# --- scope collectors ------------------------------------------------------


async def _collect_server(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime,
) -> dict[str, Any]:
    logs_root = settings.logs.root_dir
    artifacts_root = settings.artifacts.root_dir
    entries: list[dict[str, Any]] = []

    logs_bytes = await asyncio.to_thread(_du, logs_root)
    artifacts_bytes = await asyncio.to_thread(_du, artifacts_root)
    entries.append(_entry("server.logs_bytes", "bytes", logs_bytes, None))
    entries.append(
        _entry(
            "server.artifacts_bytes",
            "bytes",
            artifacts_bytes,
            _limit(settings.artifacts.max_total_bytes),
        )
    )

    # Largest single on-disk log file vs the per-file cap (pure SQL, no walk).
    # A query failure degrades only this entry (value=None -> unknown), not the
    # whole scope.
    max_bytes: int | None = None
    async with sessionmaker() as session:
        try:
            max_bytes = (
                await session.execute(select(func.max(ExecutionLogFile.size_bytes)))
            ).scalar()
        except Exception:  # noqa: BLE001
            await session.rollback()
            max_bytes = None
    entries.append(
        _entry(
            "server.max_log_file_bytes",
            "bytes",
            _num(max_bytes),
            _limit(settings.logs.max_file_bytes),
        )
    )

    for volume in _distinct_volumes(
        [settings.server.data_dir, logs_root, artifacts_root]
    ):
        usage = await asyncio.to_thread(_disk_usage, volume)
        if usage is None:
            continue
        total, used, _free = usage
        entries.append(
            _entry(f"server.volume:{volume}", "bytes", used, _limit(total))
        )

    return _scope("server", "ok", now.isoformat(), None, entries)


async def _collect_postgres(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime,
) -> dict[str, Any]:
    grace = 2 * settings.maintenance.sweep_interval_seconds
    async with sessionmaker() as session:
        bind = session.bind
        is_pg = bind is not None and bind.dialect.name == "postgresql"
        entries: list[dict[str, Any]] = []
        for name, model in _PG_TABLES.items():
            count = (
                await session.execute(select(func.count()).select_from(model))
            ).scalar() or 0
            entries.append(_entry(f"postgres.{name}_rows", "count", int(count), None))
            if is_pg:
                size = (
                    await session.execute(
                        text("SELECT pg_total_relation_size(to_regclass(:n))"),
                        {"n": name},
                    )
                ).scalar()
                entries.append(
                    _entry(f"postgres.{name}_bytes", "bytes", _num(size), None)
                )
        if is_pg:
            db_size = (
                await session.execute(
                    text("SELECT pg_database_size(current_database())")
                )
            ).scalar()
            entries.append(
                _entry("postgres.database_bytes", "bytes", _num(db_size), None)
            )

        # Oldest cleanable terminal task — uses the SAME effective-time predicate
        # as cleanup_terminal_data (COALESCE(finished_at, created_at)) so a
        # working sweep keeps this at/under the window.
        eff = func.coalesce(Task.finished_at, Task.created_at)
        oldest_task = (
            await session.execute(
                select(func.min(eff)).where(
                    Task.status.in_(tuple(states.TASK_TERMINAL))
                )
            )
        ).scalar()
        task_age = _age_seconds(oldest_task, now)
        if task_age is not None:
            entries.append(
                _entry(
                    "postgres.oldest_terminal_task_age",
                    "age",
                    task_age,
                    _limit(settings.logs.retention_days * 86400),
                    grace=grace,
                )
            )

        # Oldest event_audit row — prune_event_audit deletes by processed_at, so
        # this measures the same column.
        oldest_audit = (
            await session.execute(select(func.min(EventAudit.processed_at)))
        ).scalar()
        audit_age = _age_seconds(oldest_audit, now)
        if audit_age is not None:
            entries.append(
                _entry(
                    "postgres.oldest_event_audit_age",
                    "age",
                    audit_age,
                    _limit(
                        settings.maintenance.event_audit_retention_days * 86400
                    ),
                    grace=grace,
                )
            )

        return _scope("postgres", "ok", now.isoformat(), None, entries)


def _int_field(info: dict[str, Any], key: str) -> int | None:
    raw = info.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _stream_first_entry_age(info: dict[str, Any], now: datetime) -> int | None:
    """Age (s) of a stream's first entry, parsed from its ``<ms>-<seq>`` id."""
    first = info.get("first-entry")
    if not first:
        return None
    entry_id = first[0]
    if isinstance(entry_id, bytes):
        entry_id = entry_id.decode()
    try:
        ms = int(str(entry_id).split("-", 1)[0])
    except (ValueError, IndexError):
        return None
    return max(0, int(now.timestamp() - ms / 1000))


async def _collect_redis(
    redis_client: RedisStreamClient | None,
    settings: Settings,
    now: datetime,
    agent_ids: list[str],
) -> dict[str, Any]:
    if redis_client is None:
        return _unavailable("redis", now)
    grace = 2 * settings.maintenance.sweep_interval_seconds
    memory = await redis_client.info("memory")
    persistence = await redis_client.info("persistence")
    entries: list[dict[str, Any]] = [
        _entry(
            "redis.used_memory",
            "bytes",
            _int_field(memory, "used_memory"),
            _limit(_int_field(memory, "maxmemory")),
        ),
        _entry(
            "redis.aof_bytes",
            "bytes",
            _int_field(persistence, "aof_current_size"),
            None,
        ),
    ]

    for stream, label, maxlen_attr in (
        (LOG_STREAM, "logs", "stream_maxlen_logs"),
        (EVENT_STREAM, "events", "stream_maxlen_events"),
    ):
        info = await redis_client.xinfo_stream(stream)
        length = _int_field(info, "length") or 0
        entries.append(
            _entry(
                f"redis.stream_len:{label}",
                "count",
                length,
                _limit(getattr(settings.redis, maxlen_attr)),
            )
        )
        age = _stream_first_entry_age(info, now)
        if age is not None:
            entries.append(
                _entry(
                    f"redis.stream_age:{label}",
                    "age",
                    age,
                    _limit(settings.redis.log_retention_seconds),
                    grace=grace,
                )
            )

    # Per-agent command stream: length only. Command streams have no time-based
    # trim (old entries may be undelivered facts), so no age metric.
    for agent_id in agent_ids:
        info = await redis_client.xinfo_stream(command_stream(agent_id))
        length = _int_field(info, "length") or 0
        entries.append(
            _entry(
                f"redis.command_stream_len:{agent_id}",
                "count",
                length,
                _limit(settings.redis.stream_maxlen_commands),
            )
        )

    return _scope("redis", "ok", now.isoformat(), None, entries)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _append(
    entries: list[dict[str, Any]],
    key: str,
    kind: str,
    value: int | None,
    limit: int | None,
) -> None:
    if value is not None:
        entries.append(_entry(key, kind, value, limit))


def _agent_entries(disk: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    ws = _dict(disk.get("workspaces"))
    _append(entries, "agent.workspaces_bytes", "bytes", _num(ws.get("bytes")), None)
    _append(entries, "agent.workspaces_count", "count", _num(ws.get("count")), None)
    cache = _dict(disk.get("cache"))
    _append(
        entries,
        "agent.cache_bytes",
        "bytes",
        _num(cache.get("bytes")),
        _limit(cache.get("limit")),
    )
    scrapyd = _dict(disk.get("scrapyd"))
    _append(entries, "agent.scrapyd_bytes", "bytes", _num(scrapyd.get("bytes")), None)
    outbox = _dict(disk.get("outbox"))
    _append(
        entries,
        "agent.outbox_files",
        "count",
        _num(outbox.get("files")),
        _limit(outbox.get("limit")),
    )
    _append(entries, "agent.outbox_bytes", "bytes", _num(outbox.get("bytes")), None)
    state = _dict(disk.get("state"))
    _append(
        entries, "agent.state_executions", "count", _num(state.get("executions")), None
    )
    _append(entries, "agent.state_logpos", "count", _num(state.get("logpos")), None)
    volume = _dict(disk.get("volume"))
    used = _num(volume.get("used"))
    total = _limit(volume.get("total"))
    if used is not None:
        _append(entries, "agent.volume_used", "bytes", used, total)
    return entries


def _agent_scope(node: dict[str, Any], now: datetime) -> dict[str, Any]:
    agent_id = node["agent_id"]
    name = f"agent:{agent_id}"
    last_seen = _iso(node["last_seen_at"])
    # Availability from the DYNAMIC status (last_seen_at + heartbeat timeout),
    # not the persisted column which never flips after the agent goes quiet.
    if node["status"] in ("unhealthy", "unknown"):
        return _scope(name, "unavailable", None, last_seen, [])
    disk = node["health"].get("disk")
    if not isinstance(disk, dict):
        return _scope(name, "unavailable", None, last_seen, [])
    sampled = _parse_iso(disk.get("sampled_at"))
    interval = _num(disk.get("interval_seconds"))
    if sampled is None or not interval:
        # Can't establish freshness from a malformed sample -> unavailable.
        return _scope(name, "unavailable", None, last_seen, [])
    age = (now - sampled).total_seconds()
    status = "stale" if age > 2 * interval else "ok"
    return _scope(name, status, sampled.isoformat(), last_seen, _agent_entries(disk))


async def _read_nodes(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime,
) -> tuple[list[dict[str, Any]], bool]:
    """Return ``(nodes, ok)``. ``ok=False`` on a DB failure — the caller then
    emits an explicit ``agents`` unavailable scope instead of silently dropping
    every agent (which would misreport a DB outage as "no agents")."""
    timeout = settings.agents.heartbeat_timeout_seconds
    async with sessionmaker() as session:
        try:
            rows = (await session.execute(select(Node))).scalars().all()
        except Exception:  # noqa: BLE001
            await session.rollback()
            return [], False
        return [
            {
                "agent_id": node.agent_id,
                "last_seen_at": node.last_seen_at,
                "health": node.health or {},
                "status": _aggregate_node_status(
                    node, now=now, timeout_seconds=timeout
                ),
            }
            for node in rows
        ], True


async def _safe(coro_fn, scope_name: str, now: datetime) -> dict[str, Any]:
    try:
        return await coro_fn()
    except Exception:  # noqa: BLE001 - one scope failure never breaks the rest
        logger.error("resource_stats: %s scope failed", scope_name, exc_info=True)
        return _unavailable(scope_name, now)


async def collect_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    redis_client: RedisStreamClient | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble one resource snapshot (the two-layer scopes/entries contract).

    Each DB-backed scope opens its OWN session so a failure (e.g. an aborted
    PostgreSQL transaction) degrades only that scope. Directory walks run in a
    thread. Never raises: a crashing scope becomes ``status=unavailable``.
    """
    now = now or datetime.now(UTC)
    nodes, nodes_ok = await _read_nodes(sessionmaker, settings, now)
    agent_ids = [n["agent_id"] for n in nodes if n["agent_id"]]

    scopes = [
        await _safe(
            lambda: _collect_server(sessionmaker, settings, now), "server", now
        ),
        await _safe(
            lambda: _collect_postgres(sessionmaker, settings, now), "postgres", now
        ),
        await _safe(
            lambda: _collect_redis(redis_client, settings, now, agent_ids),
            "redis",
            now,
        ),
    ]
    if not nodes_ok:
        # DB read failed: we cannot enumerate agents, so surface the failure
        # explicitly rather than silently omitting every agent scope.
        scopes.append(_unavailable("agents", now))
    else:
        scopes.extend(_agent_scope(n, now) for n in nodes if n["agent_id"])

    return {
        "sampled_at": now.isoformat(),
        "sweep_enabled": settings.maintenance.enabled,
        "scopes": scopes,
    }


class ResourceStatsLoop:
    """Periodic resource-usage sampler (single-instance background loop)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        redis_client: RedisStreamClient | None = None,
        *,
        interval_seconds: float | None = None,
    ) -> None:
        self._sm = sessionmaker
        self._settings = settings
        self._redis = redis_client
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else float(settings.maintenance.stats_interval_seconds)
        )
        self.snapshot: dict[str, Any] | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def sample_once(self, *, now: datetime | None = None) -> None:
        """Take one snapshot and cache it. Public so tests can drive one tick."""
        self.snapshot = await collect_snapshot(
            self._sm, self._settings, self._redis, now=now
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.sample_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("resource stats sample failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
