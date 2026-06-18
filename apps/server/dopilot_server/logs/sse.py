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


class SubscriptionManager:
    """Tracks SSE subscribers per ``execution_id`` and fans out events."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, execution_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
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
        """Deliver ``event`` to every current subscriber of ``execution_id``."""
        for queue in self._subs.get(execution_id, set()):
            queue.put_nowait(event)

    def close(self, execution_id: str) -> None:
        """Signal all subscribers of ``execution_id`` to end their streams."""
        for queue in self._subs.get(execution_id, set()):
            queue.put_nowait(CLOSE)


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
