"""Server stream consumers (phase 1.5).

``EventConsumer`` drains ``dopilot:server:agent-events`` and applies each event
to PostgreSQL via :func:`dopilot_server.services.events.apply_event` (replacing
the phase-1 agent ``/status`` poll). The log consumer lives alongside it (added
in step 11).

Single-instance: the consumer group is read by exactly one server process
(``consumer_name``); XACK happens after the event is committed.
"""

from __future__ import annotations

import asyncio
import logging

from dopilot_protocol import (
    EVENT_GROUP,
    EVENT_STREAM,
    LOG_GROUP,
    LOG_STREAM,
    AgentEvent,
    AgentLogEvent,
    from_stream_entry,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config.settings import Settings
from ..logs.sse import SubscriptionManager
from ..services.events import apply_event
from ..services.logs import apply_log_event
from .commands import msg_id_to_str

logger = logging.getLogger(__name__)


class EventConsumer:
    """Consumes agent status events and converges PostgreSQL state."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        redis: object,
        *,
        consumer_name: str = "server-1",
        pending_idle_ms: int = 60000,
        block_ms: int = 5000,
        batch: int = 64,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._redis = redis
        self._consumer = consumer_name
        self._pending_idle_ms = pending_idle_ms
        self._block_ms = block_ms
        self._batch = batch
        self._stream = EVENT_STREAM
        self._group = EVENT_GROUP
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def setup(self) -> None:
        await self._redis.ensure_group(self._stream, self._group)

    async def _apply_one(self, msg_id: object, fields: object) -> None:
        event = from_stream_entry(AgentEvent, fields)
        redis_msg_id = msg_id_to_str(msg_id)
        async with self._sessionmaker() as session:
            await apply_event(session, event, redis_msg_id)
            await session.commit()
        await self._redis.xack(self._stream, self._group, msg_id)

    async def _claim_pending(self) -> int:
        processed = 0
        start = "0-0"
        for _ in range(1000):
            next_id, claimed, _deleted = await self._redis.xautoclaim(
                self._stream, self._group, self._consumer,
                self._pending_idle_ms, start, count=self._batch,
            )
            for msg_id, fields in claimed:
                await self._apply_one(msg_id, fields)
                processed += 1
            cursor = next_id.decode() if isinstance(next_id, bytes) else str(next_id)
            if not claimed or cursor in ("0-0", "0"):
                break
            start = cursor
        return processed

    async def drain_once(
        self, *, claim_pending: bool = True, block: int | None = None
    ) -> int:
        processed = 0
        if claim_pending:
            processed += await self._claim_pending()
        resp = await self._redis.xreadgroup(
            self._group, self._consumer, {self._stream: ">"},
            count=self._batch, block=block,
        )
        for _stream, entries in resp or []:
            for msg_id, fields in entries:
                await self._apply_one(msg_id, fields)
                processed += 1
        return processed

    async def _run(self) -> None:
        try:
            await self.setup()
        except Exception:  # noqa: BLE001
            logger.warning("event consumer setup failed", exc_info=True)
        while not self._stop.is_set():
            try:
                await self.drain_once(block=self._block_ms)
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("event consumer drain failed", exc_info=True)
                await asyncio.sleep(0.5)

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


class LogConsumer:
    """Consumes agent log increments and writes bodies + index + SSE.

    Replaces the phase-1 HTTP tail pull. Processes entries serially (single
    process), so per-attempt ordering is preserved without extra locking.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        redis: object,
        settings: Settings,
        manager: SubscriptionManager,
        *,
        consumer_name: str = "server-1",
        pending_idle_ms: int = 60000,
        block_ms: int = 5000,
        batch: int = 128,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._redis = redis
        self._settings = settings
        self._manager = manager
        self._consumer = consumer_name
        self._pending_idle_ms = pending_idle_ms
        self._block_ms = block_ms
        self._batch = batch
        self._stream = LOG_STREAM
        self._group = LOG_GROUP
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def setup(self) -> None:
        await self._redis.ensure_group(self._stream, self._group)

    async def _apply_one(self, msg_id: object, fields: object) -> None:
        event = from_stream_entry(AgentLogEvent, fields)
        async with self._sessionmaker() as session:
            await apply_log_event(session, self._settings, event, self._manager)
            await session.commit()
        await self._redis.xack(self._stream, self._group, msg_id)

    async def _claim_pending(self) -> int:
        processed = 0
        start = "0-0"
        for _ in range(1000):
            next_id, claimed, _deleted = await self._redis.xautoclaim(
                self._stream, self._group, self._consumer,
                self._pending_idle_ms, start, count=self._batch,
            )
            for msg_id, fields in claimed:
                await self._apply_one(msg_id, fields)
                processed += 1
            cursor = next_id.decode() if isinstance(next_id, bytes) else str(next_id)
            if not claimed or cursor in ("0-0", "0"):
                break
            start = cursor
        return processed

    async def drain_once(
        self, *, claim_pending: bool = True, block: int | None = None
    ) -> int:
        processed = 0
        if claim_pending:
            processed += await self._claim_pending()
        resp = await self._redis.xreadgroup(
            self._group, self._consumer, {self._stream: ">"},
            count=self._batch, block=block,
        )
        for _stream, entries in resp or []:
            for msg_id, fields in entries:
                await self._apply_one(msg_id, fields)
                processed += 1
        return processed

    async def _run(self) -> None:
        try:
            await self.setup()
        except Exception:  # noqa: BLE001
            logger.warning("log consumer setup failed", exc_info=True)
        while not self._stop.is_set():
            try:
                await self.drain_once(block=self._block_ms)
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("log consumer drain failed", exc_info=True)
                await asyncio.sleep(0.5)

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
