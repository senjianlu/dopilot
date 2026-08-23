"""Automatic retention sweep (resource caps, B2/B3/B4).

A single always-on background loop — the counterpart to
:class:`~dopilot_server.redis.reconcile.RedisReconcileLoop` — that enforces the
time-based retention which was previously reachable only via the manual
maintenance API. Each tick, in order:

1. deletes terminal task data older than ``logs.retention_days``
   (:func:`~dopilot_server.services.maintenance.cleanup_terminal_data`,
   failure-safe two-phase);
2. prunes ``event_audit`` rows older than
   ``maintenance.event_audit_retention_days``
   (:func:`~dopilot_server.services.maintenance.prune_event_audit`, batched);
3. time-trims the Redis log + event streams
   (:func:`~dopilot_server.services.maintenance.trim_log_streams`,
   ``XTRIM MINID``);
4. (log-flood guard) cuts sealed log files above ``logs.max_file_bytes``;
5. (log-flood guard) calibrates the logs-dir gauge and evicts the oldest sealed
   terminal tasks until ``logs.max_total_bytes`` holds;
6. (log-flood guard) deletes retired agents' command streams;
7. (log-flood guard) bounds the notification center table.

Single-instance only (matches the single-server constraint). Each step is
independently guarded so a failure in one never skips the others, and the loop
never dies. Gated by ``maintenance.enabled``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config.settings import Settings
from .logs.dir_gauge import LogsDirGauge
from .redis.client import RedisStreamClient
from .services.maintenance import (
    cleanup_terminal_data,
    delete_stale_command_streams,
    evict_logs_dir_to_budget,
    prune_event_audit,
    trim_log_streams,
    truncate_oversized_log_files,
)
from .services.notifications import prune_notifications

logger = logging.getLogger(__name__)


class RetentionSweepLoop:
    """Periodic retention sweep (single-instance background loop)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        redis_client: RedisStreamClient | None = None,
        *,
        interval_seconds: float | None = None,
        gauge: LogsDirGauge | None = None,
    ) -> None:
        self._sm = sessionmaker
        self._settings = settings
        self._redis = redis_client
        # Log-flood guard: the process-wide logs-dir gauge (shared with the
        # LogConsumer) so deletions/truncations settle the same counter.
        self._gauge = gauge
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else float(settings.maintenance.sweep_interval_seconds)
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def sweep_once(self, *, now: datetime | None = None) -> None:
        """Run one full sweep. Public so tests can drive a single tick.

        Each step is independently guarded: a failure in terminal cleanup does
        not skip event_audit pruning or the stream trim, and vice versa.
        """
        now = now or datetime.now(UTC)
        retention_days = self._settings.logs.retention_days

        # Step 1: terminal task data (owns its two-phase commits). A retention of
        # 0 means "disabled", NOT "delete everything": cutoff = now - 0 = now
        # would make every terminal task eligible and wipe all terminal history,
        # so 0 short-circuits the step (mirrors event_audit / stream-trim, which
        # already treat 0 as off). The manual sweep-now endpoint applies the same
        # guard.
        if retention_days > 0:
            cutoff = now - timedelta(days=retention_days)
            async with self._sm() as session:
                try:
                    await cleanup_terminal_data(
                        session, self._settings, cutoff=cutoff, gauge=self._gauge
                    )
                except Exception:  # noqa: BLE001 - never abort the sweep
                    logger.error(
                        "retention: terminal cleanup failed", exc_info=True
                    )
                    await session.rollback()

        # Step 2: event_audit prune (commits per batch).
        async with self._sm() as session:
            try:
                await prune_event_audit(session, self._settings, now=now)
            except Exception:  # noqa: BLE001
                logger.error(
                    "retention: event_audit prune failed", exc_info=True
                )
                await session.rollback()

        # Step 3: Redis stream time-trim (self-guards per stream).
        await trim_log_streams(self._redis, self._settings, now=now)

        # Log-flood guard steps (each independently guarded):
        # Step 4: cut SEALED log files that exceed the (possibly lowered) cap.
        async with self._sm() as session:
            try:
                await truncate_oversized_log_files(
                    session, self._settings, gauge=self._gauge
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                logger.error("retention: oversized-log truncation failed", exc_info=True)
                await session.rollback()
        # Step 5: logs-dir budget (calibrates the gauge, evicts oldest sealed).
        async with self._sm() as session:
            try:
                await evict_logs_dir_to_budget(
                    session, self._settings, gauge=self._gauge, now=now
                )
            except Exception:  # noqa: BLE001
                logger.error("retention: logs-dir budget eviction failed", exc_info=True)
                await session.rollback()
        # Step 6: retired agents' command streams.
        async with self._sm() as session:
            try:
                await delete_stale_command_streams(
                    session, self._settings, self._redis, now=now
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                logger.error("retention: stale command stream cleanup failed", exc_info=True)
                await session.rollback()
        # Step 7: notification center bounds.
        async with self._sm() as session:
            try:
                await prune_notifications(session, self._settings, now=now)
                await session.commit()
            except Exception:  # noqa: BLE001
                logger.error("retention: notification prune failed", exc_info=True)
                await session.rollback()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.sweep_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("retention sweep tick failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._interval
                )
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
