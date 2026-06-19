"""Agent log publisher (phase 1.5).

Tails each active attempt's local ``job.log`` by BYTE offset and publishes raw
byte increments (base64) to ``dopilot:server:logs``. A single sequential
producer per attempt publishes strictly increasing offsets; the durable source
is the ``job.log`` itself plus a persisted cursor, so there is no separate log
outbox: the cursor only advances after a successful XADD, so an XADD failure (or
restart) re-publishes from the cursor and the server dedups by offset. Log RPO
is non-zero by design — a Redis trim / long server stop may drop a window, which
the server surfaces as a ``partial`` gap (never a false gap from replay).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from dopilot_protocol import LOG_STREAM, AgentLogEvent, to_stream_entry

from ..state.store import StateStore

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LogPublisher:
    """Publishes per-attempt log byte increments to the shared log stream."""

    def __init__(
        self,
        *,
        redis: object,
        agent_id: str,
        store: StateStore,
        cursor_dir: str | os.PathLike[str],
        maxlen_logs: int = 1000000,
        max_bytes: int = 262144,
        interval_seconds: float = 1.0,
    ) -> None:
        self._redis = redis
        self._agent_id = agent_id
        self._store = store
        self._cursor_dir = Path(cursor_dir)
        self._maxlen = maxlen_logs
        self._max_bytes = max_bytes
        self._interval = interval_seconds
        self._eof_sent: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # --- cursor persistence ------------------------------------------------
    def _cursor_path(self, attempt_id: str) -> Path:
        return self._cursor_dir / f"{attempt_id}.logpos"

    def _read_cursor(self, attempt_id: str) -> int:
        try:
            return int(self._cursor_path(attempt_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0

    def _write_cursor(self, attempt_id: str, offset: int) -> None:
        self._cursor_dir.mkdir(parents=True, exist_ok=True)
        final = self._cursor_path(attempt_id)
        tmp = final.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(str(offset))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)

    @staticmethod
    def _read_raw(path: str, offset: int, max_bytes: int) -> bytes:
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                return fh.read(max_bytes)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return b""

    # --- publishing --------------------------------------------------------
    async def publish_attempt(self, attempt_id: str) -> int:
        """Publish all currently-available bytes of one attempt. Returns count."""
        state = self._store.read(attempt_id)
        if state is None or not state.log_path:
            return 0
        cursor = self._read_cursor(attempt_id)
        total = 0
        while True:
            raw = self._read_raw(state.log_path, cursor, self._max_bytes)
            if not raw:
                break
            event = AgentLogEvent(
                agent_id=self._agent_id,
                execution_id=state.execution_id,
                attempt_id=attempt_id,
                offset=cursor,
                content_b64=base64.b64encode(raw).decode("ascii"),
                size_bytes=len(raw),
                eof=False,
                created_at=_now(),
            )
            try:
                await self._redis.xadd(
                    LOG_STREAM, to_stream_entry(event),
                    maxlen=self._maxlen, approximate=True,
                )
            except Exception:  # noqa: BLE001 - leave cursor; retry next pass
                logger.warning("log XADD failed for %s @ %d", attempt_id, cursor)
                return total
            cursor += len(raw)
            self._write_cursor(attempt_id, cursor)
            total += len(raw)
            if len(raw) < self._max_bytes:
                break

        # terminal -> emit a single empty eof marker (optimization signal only).
        if state.phase == "done" and attempt_id not in self._eof_sent:
            eof_event = AgentLogEvent(
                agent_id=self._agent_id,
                execution_id=state.execution_id,
                attempt_id=attempt_id,
                offset=cursor,
                content_b64="",
                size_bytes=0,
                eof=True,
                created_at=_now(),
            )
            try:
                await self._redis.xadd(
                    LOG_STREAM, to_stream_entry(eof_event),
                    maxlen=self._maxlen, approximate=True,
                )
                self._eof_sent.add(attempt_id)
            except Exception:  # noqa: BLE001
                pass
        return total

    async def publish_once(self) -> int:
        """Publish increments for every attempt that has local state."""
        total = 0
        for attempt_id in self._store.list_attempt_ids():
            try:
                total += await self.publish_attempt(attempt_id)
            except Exception:  # noqa: BLE001 - isolate one bad attempt
                logger.warning("log publish failed for %s", attempt_id, exc_info=True)
        return total

    # --- background loop ---------------------------------------------------
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.publish_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("log publisher tick failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
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
