"""Thin async Redis Streams client wrapper (server side).

Exposes only the narrow surface dopilot uses (XADD / XREADGROUP / XACK /
XAUTOCLAIM / XGROUP CREATE / XLEN), so it is interchangeable with a test double
and with ``fakeredis.aioredis``. Built with ``decode_responses=False`` to keep
byte fidelity for log offset semantics (log bodies are base64 bytes).

Note: ``import redis.asyncio`` here is an absolute import and resolves to the
top-level ``redis`` library, not this ``dopilot_server.redis`` package.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import redis.asyncio as aioredis
from redis.exceptions import ResponseError


@runtime_checkable
class RedisStreamClient(Protocol):
    """The narrow Redis Streams surface dopilot depends on."""

    async def xadd(
        self,
        stream: str,
        fields: dict[Any, Any],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> Any: ...

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> Any: ...

    async def xack(self, stream: str, group: str, *ids: Any) -> int: ...

    async def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str = "0-0",
        *,
        count: int = 100,
    ) -> Any: ...

    async def ensure_group(self, stream: str, group: str) -> None: ...

    async def xlen(self, stream: str) -> int: ...

    async def aclose(self) -> None: ...


class RedisStreams:
    """Adapter over a ``redis.asyncio.Redis`` (or any compatible client)."""

    def __init__(self, client: Any) -> None:
        self._c = client

    @classmethod
    def from_url(cls, url: str) -> RedisStreams:
        return cls(aioredis.from_url(url, decode_responses=False))

    async def xadd(
        self,
        stream: str,
        fields: dict[Any, Any],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> Any:
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
        return await self._c.xreadgroup(
            group, consumer, streams, count=count, block=block
        )

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
        return await self._c.xautoclaim(
            stream, group, consumer, min_idle_ms, start, count=count
        )

    async def ensure_group(self, stream: str, group: str) -> None:
        """Idempotently create a consumer group (MKSTREAM); ignore BUSYGROUP."""
        try:
            await self._c.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:  # pragma: no cover - exercised via fake
            if "BUSYGROUP" not in str(exc):
                raise

    async def xlen(self, stream: str) -> int:
        return await self._c.xlen(stream)

    async def aclose(self) -> None:
        await self._c.aclose()


def build_redis(url: str) -> RedisStreams:
    """Build a server Redis Streams client from a connection URL."""
    return RedisStreams.from_url(url)
