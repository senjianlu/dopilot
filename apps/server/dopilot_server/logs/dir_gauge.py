"""Logs-directory byte gauge (log-flood guard, disk hard limit).

One process-wide counter of the bytes under ``logs.root_dir``, kept EXACT by a
serialisation protocol rather than by estimation:

- every mutation of the directory that dopilot performs — the log consumer's
  append, retention's truncate/unlink — runs inside ``async with gauge.writer()``
  (one ``asyncio.Lock``) and settles the counter from a before/after ``stat``
  of the file it touched (partial writes, ENOSPC and flush failures are all
  counted by what physically landed);
- ``calibrate()`` (startup + every retention sweep) holds the SAME lock across
  the whole ``os.walk``, so no write or delete can interleave with the scan and
  ``value`` equals the real directory size the moment it is reset.

The consumer may therefore admit an increment with a plain
``value + planned <= budget`` check under the lock: the directory can never
grow past ``logs.max_total_bytes`` through dopilot's own writes. Budget 0
disables admission control (the gauge still tracks).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path


def walk_size(root: str | os.PathLike[str]) -> int:
    """Total bytes of regular files under ``root`` (0 when it does not exist)."""
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def file_size(path: str | os.PathLike[str]) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


class LogsDirGauge:
    """Exact byte gauge of the logs directory (see module docstring)."""

    def __init__(self, root: str | os.PathLike[str], budget: int = 0) -> None:
        self._root = Path(root)
        self._budget = max(0, int(budget))
        self._lock = asyncio.Lock()
        self._value = 0
        self._calibrated = False
        self._calibrated_at: float | None = None

    # --- read side ---------------------------------------------------------
    @property
    def root(self) -> Path:
        return self._root

    @property
    def budget(self) -> int:
        return self._budget

    @property
    def value(self) -> int:
        return self._value

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def calibrated_at(self) -> float | None:
        return self._calibrated_at

    def fits(self, planned: int) -> bool:
        """True iff ``planned`` more bytes stay within the budget (0 = no budget)."""
        if self._budget <= 0:
            return True
        return self._value + planned <= self._budget

    # --- write side (all under the one lock) --------------------------------
    @contextlib.asynccontextmanager
    async def writer(self) -> AsyncIterator[LogsDirGauge]:
        """Serialise a directory mutation with every other mutation + calibration.

        The caller performs its stat/write/stat (or truncate/unlink) inside and
        settles the delta with :meth:`add` / :meth:`sub` BEFORE leaving.
        """
        async with self._lock:
            yield self

    def add(self, delta: int) -> None:
        """Apply a signed byte delta measured by the caller (lock must be held)."""
        self._value = max(0, self._value + int(delta))

    def sub(self, released: int) -> None:
        self.add(-int(released))

    async def calibrate(self, *, now: float | None = None) -> int:
        """Reset the gauge from a full directory walk under the lock."""
        async with self._lock:
            total = await asyncio.to_thread(walk_size, self._root)
            self._value = total
            self._calibrated = True
            self._calibrated_at = now
            return total

    # --- test / tooling helpers -----------------------------------------------
    def reset_for_tests(self, value: int) -> None:
        self._value = max(0, int(value))
        self._calibrated = True
