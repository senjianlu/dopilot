"""Log-stream BYTE budget guard (log-flood guard, Redis memory hard limit).

The per-XADD ``MAXLEN ~100000`` counts entries; at the agent's 256KB chunk size
that is a ~35GB ceiling, which is how the 2026-08-21 incident filled Redis.
``StreamGuardLoop`` measures the log stream's real footprint with
``MEMORY USAGE <stream> SAMPLES 0`` (exact) every ``stream_guard_interval_seconds``
— and once at startup, BEFORE the consumers start — and trims it back under
``redis.stream_max_bytes_logs``:

- iterative **exact** ``XTRIM MAXLEN = target`` (no ``~``) with a conservative
  target ``floor(len * budget/usage * 0.8)``, re-measuring after each cut, up to
  ``MAX_ROUNDS``;
- if a round shrinks usage by less than ``MIN_PROGRESS`` (very uneven entries)
  or the budget is still exceeded after ``MAX_ROUNDS``, the stream is
  **cleared** (``XTRIM MAXLEN 0``): it is a transient bus (decision 0008) whose
  non-zero log RPO is already by design, and an unbounded Redis is fatal.

Each trim raises a ``redis_stream_over_budget`` notification (warning, key
``trim:<hour>``); a clear raises an error-severity one (key ``cleared:<hour>``)
so the two never fold into each other.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime
from typing import Any

from dopilot_protocol import LOG_STREAM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config.settings import Settings
from ..models.notification import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    TYPE_REDIS_STREAM_OVER_BUDGET,
)
from ..services import notifications as notif
from .client import RedisStreamClient

logger = logging.getLogger(__name__)

MAX_ROUNDS = 8
SHRINK_FACTOR = 0.8
MIN_PROGRESS = 0.05


class StreamGuardLoop:
    """Periodic byte-budget enforcement for the shared log stream."""

    def __init__(
        self,
        redis: RedisStreamClient,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        stream: str = LOG_STREAM,
        interval_seconds: float | None = None,
        now: Any = None,
    ) -> None:
        self._redis = redis
        self._settings = settings
        self._sm = sessionmaker
        self._stream = stream
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else float(settings.redis.stream_guard_interval_seconds)
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_result: dict[str, Any] | None = None

    @property
    def budget(self) -> int:
        return max(0, int(self._settings.redis.stream_max_bytes_logs))

    # --- one enforcement pass ----------------------------------------------
    async def measure(self) -> tuple[int, int]:
        """``(usage_bytes, length)`` of the stream (0, 0 when it does not exist)."""
        usage = await self._redis.memory_usage(self._stream, samples=0)
        length = await self._redis.xlen(self._stream)
        return int(usage or 0), int(length or 0)

    async def enforce_once(self) -> dict[str, Any]:
        """Trim the stream under budget; returns a result dict (also stored)."""
        budget = self.budget
        result: dict[str, Any] = {
            "trimmed": 0, "iterations": 0, "cleared": False, "final_bytes": 0,
            "initial_bytes": 0, "budget": budget,
        }
        if budget <= 0:
            self.last_result = result
            return result
        usage, length = await self.measure()
        result["initial_bytes"] = usage
        result["final_bytes"] = usage
        if usage <= budget or length == 0:
            self.last_result = result
            return result

        trimmed_total = 0
        rounds = 0
        cleared = False
        while usage > budget and rounds < MAX_ROUNDS:
            rounds += 1
            target = int(math.floor(length * (budget / usage) * SHRINK_FACTOR))
            target = max(0, min(target, length - 1))
            removed = await self._redis.xtrim(self._stream, maxlen=target, approximate=False)
            trimmed_total += int(removed or 0)
            new_usage, new_length = await self.measure()
            progress = (usage - new_usage) / usage if usage else 1.0
            usage, length = new_usage, new_length
            if length == 0:
                # the conservative target reached zero: the stream is gone,
                # which IS a clear (report it as such).
                cleared = True
                break
            if usage > budget and progress < MIN_PROGRESS:
                logger.warning(
                    "stream guard: %s shrank only %.1f%% in round %d; clearing",
                    self._stream, progress * 100, rounds,
                )
                cleared = True
                break
        if usage > budget and not cleared and length > 0:
            logger.warning(
                "stream guard: %s still %d > %d after %d rounds; clearing",
                self._stream, usage, budget, rounds,
            )
            cleared = True
        if cleared and length > 0:
            removed = await self._redis.xtrim(self._stream, maxlen=0, approximate=False)
            trimmed_total += int(removed or 0)
            usage, length = await self.measure()

        result.update(
            trimmed=trimmed_total, iterations=rounds, cleared=cleared, final_bytes=usage
        )
        self.last_result = result
        await self._notify(result)
        return result

    async def _notify(self, result: dict[str, Any]) -> None:
        if self._sm is None or result["trimmed"] <= 0 and not result["cleared"]:
            return
        hour = self._now().strftime("%Y-%m-%dT%H")
        if result["cleared"]:
            severity, key = SEVERITY_ERROR, f"cleared:{hour}"
        else:
            severity, key = SEVERITY_WARNING, f"trim:{hour}"
        payload = {
            "stream": self._stream,
            "budget": result["budget"],
            "initial_bytes": result["initial_bytes"],
            "final_bytes": result["final_bytes"],
            "trimmed": result["trimmed"],
            "iterations": result["iterations"],
            "cleared": result["cleared"],
        }
        try:
            async with self._sm() as session:
                await notif.notify(
                    session,
                    type=TYPE_REDIS_STREAM_OVER_BUDGET,
                    severity=severity,
                    payload=payload,
                    dedupe_key=key,
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - alerting never breaks the guard
            logger.warning("stream guard notification failed", exc_info=True)

    # --- background loop ----------------------------------------------------
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.enforce_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("stream guard tick failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None and self._interval > 0:
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
