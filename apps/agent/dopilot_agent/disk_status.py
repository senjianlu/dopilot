"""Shared agent disk-usage sample (resource dashboard, D1).

A tiny thread-safe single-value container. The janitor loop (running its FS
walks in a worker thread) publishes a fixed-shape sample here each sweep; the
heartbeat worker reads the latest sample and attaches it to ``detail["disk"]``.
The heartbeat path therefore NEVER walks the filesystem — it only reads the
cached snapshot.

Lives in its own module (not ``deps``) so both ``deps`` and ``redis.heartbeat``
can import it without a circular import (``deps`` imports ``HeartbeatWorker``).
"""

from __future__ import annotations

import threading
from typing import Any


class DiskStatus:
    """Thread-safe holder for the most recent agent disk-usage sample."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sample: dict[str, Any] | None = None

    def update(self, sample: dict[str, Any]) -> None:
        with self._lock:
            self._sample = sample

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return self._sample
