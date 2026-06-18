"""Background reconcile loop (started in the app lifespan; workers=1 only).

One in-process loop drains active executions' logs and polls their status:

- cold executions drain every ``background_drain_interval_seconds``;
- an execution with an open web log window (a live SSE subscriber) drains every
  ``realtime_drain_interval_seconds``;
- each attempt's agent ``/status`` is polled every
  ``status_poll_interval_seconds``; a terminal status triggers the final drain;
- an attempt whose agent stays unreachable (or ``unknown``) longer than
  ``unreachable_lost_seconds`` is declared ``lost`` (never stuck running).

On server restart the loop re-loads active/finalizing executions straight from
the DB and resumes — its in-memory cadence/failure state is rebuildable.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..clients.agent import AgentClient
from ..config.settings import Settings
from ..models.execution import Execution, ExecutionAttempt
from ..nodes.service import refresh_nodes
from ..services import states
from . import reconcile
from .sse import SubscriptionManager

logger = logging.getLogger("dopilot_server.logs.loop")


class ReconcileLoop:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        settings: Settings,
        agent_client: AgentClient,
        manager: SubscriptionManager,
        *,
        refresh_nodes_enabled: bool = True,
    ) -> None:
        self._sm = sessionmaker
        self._settings = settings
        self._agent = agent_client
        self._manager = manager
        self._refresh_nodes = refresh_nodes_enabled
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_drain: dict[str, float] = {}
        self._last_poll: dict[str, float] = {}
        self._unreachable_since: dict[str, float] = {}
        self._last_node_refresh = 0.0
        # Attempts whose final drain is running in a detached task (so the main
        # tick is never blocked by a finalize) + the tasks themselves.
        self._finalizing: set[str] = set()
        self._finalize_tasks: set[asyncio.Task] = set()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for task in list(self._finalize_tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._finalize_tasks.clear()
        self._finalizing.clear()

    async def _run(self) -> None:
        tick = max(self._settings.logs.realtime_drain_interval_seconds, 1)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 - loop must never die
                logger.exception("reconcile tick failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=tick)

    async def _tick(self) -> None:
        now = time.monotonic()
        async with self._sm() as session:
            if self._refresh_nodes and (
                now - self._last_node_refresh
                >= self._settings.logs.background_drain_interval_seconds
            ):
                self._last_node_refresh = now
                with contextlib.suppress(Exception):
                    await refresh_nodes(session, self._settings)

            result = await session.execute(
                select(ExecutionAttempt)
                .join(Execution, ExecutionAttempt.execution_id == Execution.id)
                .where(
                    Execution.status.in_(tuple(states.EXEC_ACTIVE)),
                    ExecutionAttempt.status.in_(tuple(states.ATTEMPT_ACTIVE)),
                )
            )
            attempts = list(result.scalars().all())
            hot = self._manager.hot_execution_ids()
            for attempt in attempts:
                try:
                    await self._process(session, attempt, hot, now)
                except Exception:  # noqa: BLE001 - isolate one bad attempt
                    logger.exception(
                        "reconcile failed for attempt %s", attempt.id
                    )

    async def _process(
        self,
        session,
        attempt: ExecutionAttempt,
        hot: set[str],
        _now: float,
    ) -> None:
        # A finalize for this attempt may be running in a detached task; skip it
        # entirely so we never drain it concurrently from two sessions.
        if attempt.id in self._finalizing:
            return
        # Re-read the clock per attempt: a finalize/await earlier in the tick can
        # make a single tick-start timestamp stale, which would skew lost timers.
        now = time.monotonic()
        log_cfg = self._settings.logs
        is_hot = attempt.execution_id in hot
        drain_interval = (
            log_cfg.realtime_drain_interval_seconds
            if is_hot
            else log_cfg.background_drain_interval_seconds
        )

        if now - self._last_drain.get(attempt.id, 0.0) >= drain_interval:
            self._last_drain[attempt.id] = now
            log_file = await reconcile.svc.get_log_file(
                session, attempt.execution_id, attempt.id
            )
            if log_file is not None:
                # A successful drain says nothing about liveness, so it does NOT
                # clear the lost timer (only a positive /status does, below).
                try:
                    await reconcile.drain_attempt(
                        session,
                        self._settings,
                        self._agent,
                        self._manager,
                        attempt,
                        log_file,
                    )
                except Exception:  # noqa: BLE001 - unreachable during drain
                    self._unreachable_since.setdefault(attempt.id, now)

        if now - self._last_poll.get(attempt.id, 0.0) >= log_cfg.status_poll_interval_seconds:
            self._last_poll[attempt.id] = now
            st = await reconcile.poll_attempt_status(self._agent, attempt)
            if st is None:
                await self._maybe_lost(session, attempt, now, "unreachable")
                return
            target = states.AGENT_TO_ATTEMPT.get(st.status)
            if target in states.ATTEMPT_TERMINAL:
                self._unreachable_since.pop(attempt.id, None)
                self._start_finalize(attempt.id, target, st.exit_code)
            elif target == states.ATTEMPT_RUNNING:
                self._unreachable_since.pop(attempt.id, None)
                if attempt.status == states.ATTEMPT_PENDING:
                    attempt.status = states.ATTEMPT_RUNNING
                    await session.commit()
            else:  # unknown (agent reachable but cannot resolve the attempt)
                await self._maybe_lost(session, attempt, now, "status_unknown")

    def _start_finalize(
        self, attempt_id: str, target: str, exit_code: int | None
    ) -> None:
        """Run the (bounded but slow) final drain off the main reconcile tick."""
        if attempt_id in self._finalizing:
            return
        self._finalizing.add(attempt_id)
        task = asyncio.create_task(
            self._finalize_task(attempt_id, target, exit_code)
        )
        self._finalize_tasks.add(task)
        task.add_done_callback(self._finalize_tasks.discard)

    async def _finalize_task(
        self, attempt_id: str, target: str, exit_code: int | None
    ) -> None:
        try:
            async with self._sm() as session:
                attempt = await session.get(ExecutionAttempt, attempt_id)
                if attempt is not None and attempt.status in states.ATTEMPT_ACTIVE:
                    await reconcile.finalize_attempt(
                        session,
                        self._settings,
                        self._agent,
                        self._manager,
                        attempt,
                        target,
                        exit_code=exit_code,
                    )
        except Exception:  # noqa: BLE001 - a finalize must not kill the loop
            logger.exception("finalize failed for attempt %s", attempt_id)
        finally:
            self._finalizing.discard(attempt_id)

    async def _maybe_lost(
        self, session, attempt: ExecutionAttempt, now: float, reason: str
    ) -> bool:
        since = self._unreachable_since.setdefault(attempt.id, now)
        if now - since >= self._settings.logs.unreachable_lost_seconds:
            await reconcile.mark_attempt_lost(
                session, self._manager, attempt, reason
            )
            self._unreachable_since.pop(attempt.id, None)
            return True
        return False
