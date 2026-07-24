"""In-memory SSE fan-out (single process, uvicorn workers=1).

Multiple web log windows watching the same execution share ONE pull loop and a
single fan-out: each open SSE connection registers a queue here; the reconcile
loop publishes increments once and they are delivered to every subscriber. No
Redis/NATS/pub-sub — the v1 single-instance constraint makes in-memory enough.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Request

# A terminal sentinel pushed onto a subscriber queue so its generator can stop.
CLOSE = object()

# Resource caps (B6): per-subscriber queue bound. A subscriber whose generator
# stalls (slow/stuck client) must never let the publisher grow an unbounded queue
# and exhaust RAM; once this many undelivered events pile up the subscriber is
# force-closed (its generator ends, the client reconnects and re-tails).
DEFAULT_QUEUE_MAXSIZE = 1000


class SubscriptionManager:
    """Tracks SSE subscribers per ``execution_id`` and fans out events."""

    def __init__(self, *, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._maxsize = queue_maxsize

    def subscribe(self, execution_id: str) -> asyncio.Queue:
        # Bounded queue (resource caps, B6): a stalled subscriber cannot grow it
        # without limit — the publisher force-closes it on overflow instead.
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs.setdefault(execution_id, set()).add(queue)
        return queue

    def unsubscribe(self, execution_id: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(execution_id)
        if not subs:
            return
        subs.discard(queue)
        if not subs:
            self._subs.pop(execution_id, None)

    def subscriber_count(self, execution_id: str) -> int:
        return len(self._subs.get(execution_id, ()))

    def hot_execution_ids(self) -> set[str]:
        """Executions with at least one open log window (realtime cadence)."""
        return {eid for eid, subs in self._subs.items() if subs}

    def publish(self, execution_id: str, event: dict[str, Any]) -> None:
        """Deliver ``event`` to every current subscriber of ``execution_id``.

        Iterates over a snapshot so an overflow-triggered unsubscribe can mutate
        the set mid-loop. A subscriber whose bounded queue is full is force-closed
        (see :meth:`_overflow`) rather than silently dropped or blocked on.
        """
        for queue in list(self._subs.get(execution_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._overflow(execution_id, queue)

    def close(self, execution_id: str) -> None:
        """Signal all subscribers of ``execution_id`` to end their streams."""
        for queue in list(self._subs.get(execution_id, ())):
            self._push_close(queue)

    def _overflow(self, execution_id: str, queue: asyncio.Queue) -> None:
        """Force-close a subscriber whose queue overflowed (resource caps, B6).

        The generator is blocked on ``queue.get()``; draining the backlog and
        pushing :data:`CLOSE` wakes it so it ends promptly (``finally`` then
        unsubscribes). The web client reconnects and re-tails from its last
        offset via the existing recovery path — no data is lost, only this stalled
        connection is dropped. Also unsubscribed here so a wedged generator that
        never wakes still stops receiving fan-out.
        """
        self._push_close(queue)
        self.unsubscribe(execution_id, queue)

    @staticmethod
    def _push_close(queue: asyncio.Queue) -> None:
        """Drain any backlog (to guarantee room) then push :data:`CLOSE`."""
        try:
            while True:
                queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(CLOSE)
        except asyncio.QueueFull:  # pragma: no cover - just drained, room exists
            pass


def get_subscriptions(request: Request) -> SubscriptionManager:
    """FastAPI dependency returning the app-wide :class:`SubscriptionManager`.

    Built in ``create_app`` and stored on ``app.state`` (so it exists with or
    without the lifespan having run — tests use ASGITransport).
    """
    manager = getattr(request.app.state, "subscriptions", None)
    if manager is None:  # pragma: no cover - defensive; create_app sets it
        manager = SubscriptionManager()
        request.app.state.subscriptions = manager
    return manager
