"""TC-24: notification center service + API (dedupe, severity, bounds, auth)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from dopilot_server.models.notification import (
    TYPE_LOG_FLOOD,
    TYPE_LOG_TRUNCATED,
    TYPE_REDIS_STREAM_OVER_BUDGET,
    Notification,
)
from dopilot_server.services import notifications as svc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import make_settings


async def _count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Notification))).scalar_one())


async def test_dedupe_folds_into_one_unread_row(db_session: AsyncSession) -> None:
    a = await svc.notify(db_session, type=TYPE_LOG_FLOOD, dedupe_key="x1", payload={"n": 1})
    b = await svc.notify(db_session, type=TYPE_LOG_FLOOD, dedupe_key="x1", payload={"n": 2})
    await db_session.commit()
    assert a == b
    rows = await svc.list_notifications(db_session)
    assert len(rows) == 1 and rows[0].count == 2 and rows[0].payload["n"] == 2
    # After read, the same key starts a fresh row.
    assert await svc.mark_read(db_session, [a]) == 1
    c = await svc.notify(db_session, type=TYPE_LOG_FLOOD, dedupe_key="x1")
    await db_session.commit()
    assert c != a and await _count(db_session) == 2
    assert await svc.unread_count(db_session) == 1


async def test_same_execution_different_types_are_independent(db_session: AsyncSession) -> None:
    await svc.notify(db_session, type=TYPE_LOG_TRUNCATED, dedupe_key="ex-1")
    await svc.notify(db_session, type=TYPE_LOG_FLOOD, dedupe_key="ex-1")
    await db_session.commit()
    rows = await svc.list_notifications(db_session)
    assert sorted(r.type for r in rows) == [TYPE_LOG_FLOOD, TYPE_LOG_TRUNCATED]
    assert all(r.count == 1 for r in rows)


async def test_severity_only_rises_and_cleared_is_sticky(db_session: AsyncSession) -> None:
    key = "trim:2026-08-21T12"
    # error then warning -> stays error, cleared stays true
    await svc.notify(
        db_session, type=TYPE_REDIS_STREAM_OVER_BUDGET, severity="error",
        dedupe_key=key, payload={"cleared": True, "trimmed": 0},
    )
    await svc.notify(
        db_session, type=TYPE_REDIS_STREAM_OVER_BUDGET, severity="warning",
        dedupe_key=key, payload={"cleared": False, "trimmed": 10},
    )
    await db_session.commit()
    row = (await svc.list_notifications(db_session))[0]
    assert row.severity == "error" and row.payload["cleared"] is True
    assert row.payload["trimmed"] == 10 and row.count == 2
    # warning then error -> rises to error
    await svc.notify(db_session, type=TYPE_LOG_FLOOD, severity="warning", dedupe_key="k2")
    await svc.notify(db_session, type=TYPE_LOG_FLOOD, severity="error", dedupe_key="k2")
    await db_session.commit()
    row = next(r for r in await svc.list_notifications(db_session) if r.dedupe_key == "k2")
    assert row.severity == "error"


async def test_prune_bounds_table(db_session: AsyncSession) -> None:
    settings = make_settings()
    settings.maintenance.notification_retention_days = 30
    settings.maintenance.notification_unread_max_days = 90
    settings.maintenance.notification_max_rows = 2000
    now = datetime.now(UTC)
    old_read = Notification(type="t", severity="info", payload={}, count=1,
                            read_at=now - timedelta(days=31),
                            created_at=now - timedelta(days=31), updated_at=now,
                            last_seen_at=now)
    fresh_read = Notification(type="t", severity="info", payload={}, count=1,
                              read_at=now, created_at=now - timedelta(days=1),
                              updated_at=now, last_seen_at=now)
    old_unread = Notification(type="t", severity="info", payload={}, count=1,
                              created_at=now - timedelta(days=91), updated_at=now,
                              last_seen_at=now)
    db_session.add_all([old_read, fresh_read, old_unread])
    await db_session.commit()
    out = await svc.prune_notifications(db_session, settings, now=now)
    await db_session.commit()
    assert out["read_expired"] == 1 and out["unread_expired"] == 1
    assert await _count(db_session) == 1

    # 2100 never-read rows -> capped at 2000, oldest first
    base = now - timedelta(days=10)
    db_session.add_all(
        [
            Notification(type="bulk", severity="info", payload={"i": i}, count=1,
                         created_at=base + timedelta(seconds=i), updated_at=now,
                         last_seen_at=now)
            for i in range(2100)
        ]
    )
    await db_session.commit()
    out = await svc.prune_notifications(db_session, settings, now=now)
    await db_session.commit()
    assert out["over_cap"] == 101
    assert await _count(db_session) == 2000
    oldest = (
        await db_session.execute(
            select(Notification.payload).where(Notification.type == "bulk")
            .order_by(Notification.created_at.asc()).limit(1)
        )
    ).scalar_one()
    # the read row (fresh_read) was evicted first, then the 100 oldest unread
    assert oldest["i"] == 100


async def test_api_list_count_read_and_auth(client, client_auth_on, db_session) -> None:
    await svc.notify(db_session, type=TYPE_LOG_FLOOD, dedupe_key="e1",
                     payload={"task_id": "t1"})
    await svc.notify(db_session, type=TYPE_LOG_TRUNCATED, dedupe_key="e2")
    await db_session.commit()

    resp = await client.get("/api/v1/notifications/unread-count")
    assert resp.status_code == 200 and resp.json()["unread_count"] == 2

    resp = await client.get("/api/v1/notifications", params={"unread_only": "true"})
    body = resp.json()
    assert resp.status_code == 200 and len(body["notifications"]) == 2
    assert body["unread_count"] == 2
    first = body["notifications"][0]
    assert {"id", "type", "severity", "payload", "count", "read", "created_at"} <= set(first)
    assert "_sticky" not in first["payload"]

    resp = await client.post("/api/v1/notifications/read", json={"ids": [first["id"]]})
    assert resp.status_code == 200 and resp.json()["marked"] == 1
    resp = await client.get("/api/v1/notifications", params={"unread_only": "true"})
    assert len(resp.json()["notifications"]) == 1

    resp = await client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 200 and resp.json()["marked"] == 1
    assert (await client.get("/api/v1/notifications/unread-count")).json()["unread_count"] == 0

    resp = await client.get("/api/v1/notifications", params={"before": "not-a-date"})
    assert resp.status_code == 400

    # auth on + no bearer -> 401 on every endpoint
    for method, path in (
        ("get", "/api/v1/notifications"),
        ("get", "/api/v1/notifications/unread-count"),
        ("post", "/api/v1/notifications/read"),
        ("post", "/api/v1/notifications/read-all"),
    ):
        resp = await getattr(client_auth_on, method)(
            path, **({"json": {"ids": []}} if path.endswith("/read") else {})
        )
        assert resp.status_code == 401, path


async def test_concurrent_notify_same_key_is_atomic_on_postgres(pg_sessionmaker) -> None:
    """Three independent sessions upsert the same key at once -> one row, count 3."""

    async def one() -> None:
        async with pg_sessionmaker() as s:
            await svc.notify(s, type=TYPE_LOG_FLOOD, dedupe_key="pg-race")
            await s.commit()

    await asyncio.gather(one(), one(), one())
    async with pg_sessionmaker() as s:
        rows = await svc.list_notifications(s)
        assert len(rows) == 1 and rows[0].count == 3
        # A direct second unread insert with the same key violates the index.
        s.add(Notification(type=TYPE_LOG_FLOOD, dedupe_key="pg-race", payload={}))
        with pytest.raises(Exception):  # noqa: B017 - IntegrityError family
            await s.flush()
