"""Notification center service (log-flood guard / auto-disable).

``notify`` is the single write path every producer uses (event consumer, log
consumer, stream guard, retention sweep, dispatcher). With a ``dedupe_key`` it
is an ATOMIC upsert against the partial unique index
``uq_notifications_active_dedupe (type, dedupe_key) WHERE read_at IS NULL``:
two sessions raising the same alert concurrently end up with ONE unread row
whose ``count`` is incremented; ``severity`` is only ever raised (info <
warning < error) and sticky boolean payload flags (``cleared``, ``escalation``
markers) are never reset by a later, milder occurrence. Once a row is read, the
same key starts a fresh row.

Both PostgreSQL and SQLite support ``INSERT ... ON CONFLICT ... WHERE`` with a
partial-index target, so the same statement runs under aiosqlite in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, func, literal, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..models.notification import (
    SEVERITY_RANK,
    SEVERITY_WARNING,
    Notification,
    _new_id,
)

# Payload keys that are sticky-true across upserts (a later milder event must
# not erase the fact that the stream was cleared / the crawler was killed).
STICKY_FLAGS = ("cleared",)


def _now() -> datetime:
    return datetime.now(UTC)


def _dialect_insert(session: AsyncSession):
    name = session.get_bind().dialect.name
    return sqlite.insert if name == "sqlite" else postgresql.insert


async def notify(
    session: AsyncSession,
    *,
    type: str,
    severity: str = SEVERITY_WARNING,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> str:
    """Record a notification; returns the row id written or updated.

    Caller commits. Without ``dedupe_key`` a fresh row is always inserted.
    """
    payload = dict(payload or {})
    now = _now()
    if severity not in SEVERITY_RANK:
        raise ValueError(f"unknown severity {severity!r}")
    if dedupe_key is None:
        row = Notification(
            type=type, severity=severity, payload=payload, dedupe_key=None,
            count=1, created_at=now, updated_at=now, last_seen_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id

    insert = _dialect_insert(session)
    new_id = _new_id()
    new_rank = SEVERITY_RANK[severity]
    existing_rank = case(
        (Notification.severity == "error", 2),
        (Notification.severity == "warning", 1),
        else_=0,
    )
    stmt = insert(Notification).values(
        id=new_id, type=type, severity=severity, payload=payload,
        dedupe_key=dedupe_key, count=1, read_at=None,
        created_at=now, updated_at=now, last_seen_at=now,
    )
    # Atomic on conflict: count+1, freshen timestamps, and raise (never lower)
    # the severity — all SQL-side so concurrent writers cannot lose updates.
    stmt = stmt.on_conflict_do_update(
        index_elements=[Notification.type, Notification.dedupe_key],
        index_where=Notification.read_at.is_(None),
        set_={
            "count": Notification.count + 1,
            "last_seen_at": now,
            "updated_at": now,
            "severity": case(
                (existing_rank < new_rank, literal(severity)),
                else_=Notification.severity,
            ),
        },
    )
    await session.execute(stmt)
    row = (
        await session.execute(
            select(Notification).where(
                Notification.type == type,
                Notification.dedupe_key == dedupe_key,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    if row.id != new_id:
        # Folded into an existing unread row: refresh the payload but keep any
        # sticky flag that was already true (a milder later event must not
        # erase e.g. ``cleared=true``).
        merged = dict(row.payload or {})
        sticky = {k for k in STICKY_FLAGS if merged.get(k) is True}
        merged.update(payload)
        for key in sticky:
            merged[key] = True
        row.payload = merged
        await session.flush()
    return row.id


async def list_notifications(
    session: AsyncSession,
    *,
    unread_only: bool = False,
    limit: int = 20,
    before: datetime | None = None,
) -> list[Notification]:
    stmt = select(Notification)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before is not None:
        stmt = stmt.where(Notification.created_at < before)
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def unread_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.read_at.is_(None)
                )
            )
        ).scalar_one()
    )


async def mark_read(session: AsyncSession, ids: list[str]) -> int:
    if not ids:
        return 0
    now = _now()
    result = await session.execute(
        update(Notification)
        .where(Notification.id.in_(ids), Notification.read_at.is_(None))
        .values(read_at=now, updated_at=now)
    )
    return int(result.rowcount or 0)


async def mark_all_read(session: AsyncSession) -> int:
    now = _now()
    result = await session.execute(
        update(Notification)
        .where(Notification.read_at.is_(None))
        .values(read_at=now, updated_at=now)
    )
    return int(result.rowcount or 0)


async def prune_notifications(
    session: AsyncSession, settings: Settings, *, now: datetime | None = None
) -> dict[str, int]:
    """Bound the table (decision 0019). Caller commits.

    1. read rows older than ``notification_retention_days``;
    2. UNREAD rows older than ``notification_unread_max_days``;
    3. anything beyond ``notification_max_rows`` — oldest first, read rows
       before unread ones.
    """
    now = now or _now()
    m = settings.maintenance
    out = {"read_expired": 0, "unread_expired": 0, "over_cap": 0}
    if m.notification_retention_days > 0:
        cutoff = now - timedelta(days=m.notification_retention_days)
        res = await session.execute(
            delete(Notification).where(
                Notification.read_at.is_not(None), Notification.created_at < cutoff
            )
        )
        out["read_expired"] = int(res.rowcount or 0)
    if m.notification_unread_max_days > 0:
        cutoff = now - timedelta(days=m.notification_unread_max_days)
        res = await session.execute(
            delete(Notification).where(
                Notification.read_at.is_(None), Notification.created_at < cutoff
            )
        )
        out["unread_expired"] = int(res.rowcount or 0)
    if m.notification_max_rows > 0:
        total = int(
            (await session.execute(select(func.count()).select_from(Notification))).scalar_one()
        )
        excess = total - m.notification_max_rows
        if excess > 0:
            # read rows first (oldest), then unread (oldest)
            victims = (
                await session.execute(
                    select(Notification.id)
                    .order_by(
                        Notification.read_at.is_(None),  # False (read) sorts first
                        Notification.created_at.asc(),
                        Notification.id.asc(),
                    )
                    .limit(excess)
                )
            ).scalars().all()
            res = await session.execute(
                delete(Notification).where(Notification.id.in_(list(victims)))
            )
            out["over_cap"] = int(res.rowcount or 0)
    return out


def notification_view(row: Notification) -> dict[str, Any]:
    payload = {k: v for k, v in (row.payload or {}).items() if k != "_sticky"}
    return {
        "id": row.id,
        "type": row.type,
        "severity": row.severity,
        "payload": payload,
        "count": row.count,
        "read": row.read_at is not None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
    }
