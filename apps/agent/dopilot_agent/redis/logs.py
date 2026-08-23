"""Agent log publisher (phase 1.5).

Tails each active attempt's local ``job.log`` by BYTE offset and publishes raw
byte increments (base64) to ``dopilot:server:logs``. A single sequential
producer per attempt publishes strictly increasing offsets; the durable source
is the ``job.log`` itself plus a persisted cursor, so there is no separate log
outbox: the cursor only advances after a successful XADD, so an XADD failure (or
restart) re-publishes from the cursor and the server dedups by offset. Log RPO
is non-zero by design — a Redis trim / long server stop may drop a window, which
the server surfaces as a ``partial`` gap (never a false gap from replay).

Log-flood guard (resource caps): two bounds sit on top of the tail loop.

- **Per-execution byte cap** (``max_job_log_bytes``, 0 = off): once an
  execution's published bytes reach the cap the publisher emits ONE entry whose
  content is a truncation marker, persists ``log_capped`` in the state file and
  never tails that execution again (its EOF marker is still sent at terminal).
  A server ``stop_logs`` backpressure command reaches the same state via
  :meth:`LogPublisher.cap`.
- **Agent-wide token bucket** (``log_publish_rate_bytes_per_second``, 0 = off):
  bounds how many log bytes per second this agent pushes into the shared
  stream however many executions are talkative (bucket = 2s of quota). EVERY
  entry body counts — content and truncation markers alike — so the bytes
  that actually land in Redis per tick never exceed the bucket. When the
  bucket runs dry the remaining executions wait for the next tick; the scan
  order rotates so no execution starves.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from dopilot_protocol import LOG_STREAM, AgentLogEvent, to_stream_entry

from ..state.store import StateStore
from .status import RedisRuntimeStatus

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
        maxlen_logs: int = 100000,
        max_bytes: int = 262144,
        interval_seconds: float = 1.0,
        status: RedisRuntimeStatus | None = None,
        on_eof: Callable[[str], None] | None = None,
        max_job_log_bytes: int = 0,
        rate_bytes_per_second: int = 0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._redis = redis
        self._agent_id = agent_id
        self._store = store
        self._cursor_dir = Path(cursor_dir)
        self._maxlen = maxlen_logs
        self._max_bytes = max_bytes
        self._interval = interval_seconds
        self._eof_sent: set[str] = set()
        # Log-flood guard: per-execution publish cap + agent-wide token bucket.
        self._cap = max(0, int(max_job_log_bytes))
        self._rate = max(0, int(rate_bytes_per_second))
        self._bucket_capacity = float(self._rate * 2)
        if self._rate > 0 and self._bucket_capacity < len(self._marker()):
            # Settings already reject this (LOG_PUBLISH_RATE_MIN); keep the
            # invariant local so the bucket is NEVER overshot by a marker.
            raise ValueError(
                "rate_bytes_per_second too low: the 2s bucket cannot hold one "
                f"truncation marker ({len(self._marker())} bytes)"
            )
        self._tokens = self._bucket_capacity
        self._clock = clock
        self._last_refill = clock()
        self._rotate_from = 0
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._status = status
        # Resource caps (C6): invoked once, right after an execution's EOF is
        # published, so the consumer can drop terminal-execution bookkeeping that
        # is safe to release at EOF (in-proc-wheel set + runner dicts). It must NOT
        # touch _eof_sent, which stays until state cleanup to keep EOF idempotent.
        self._on_eof = on_eof

    # --- cursor persistence ------------------------------------------------
    def _cursor_path(self, execution_id: str) -> Path:
        return self._cursor_dir / f"{execution_id}.logpos"

    def _read_cursor(self, execution_id: str) -> int:
        try:
            return int(self._cursor_path(execution_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0

    def _write_cursor(self, execution_id: str, offset: int) -> None:
        self._cursor_dir.mkdir(parents=True, exist_ok=True)
        final = self._cursor_path(execution_id)
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

    # --- log-flood guard helpers --------------------------------------------
    def _refill(self) -> None:
        if self._rate <= 0:
            return
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._last_refill = now
        self._tokens = min(self._bucket_capacity, self._tokens + elapsed * self._rate)

    def _allowance(self) -> int:
        """Bytes the bucket allows right now (unbounded when rate is 0)."""
        if self._rate <= 0:
            return self._max_bytes
        return int(self._tokens)

    def _spend(self, n: int) -> None:
        if self._rate > 0:
            self._tokens = max(0.0, self._tokens - n)

    def cap(self, execution_id: str) -> None:
        """Stop tailing ``execution_id`` (server ``stop_logs`` backpressure)."""
        self._store.mark_log_capped(execution_id)

    def _marker(self) -> bytes:
        return f"\n[dopilot:log-truncated max_bytes={self._cap} reason=size-cap]\n".encode()

    def _content_cap(self) -> int:
        """Bytes of real content allowed per execution: the cap minus the
        marker, so content + marker together never exceed ``max_job_log_bytes``."""
        return max(0, self._cap - len(self._marker()))

    def _marker_allowed(self, allowance: int, marker_len: int) -> bool:
        """Whether the bucket can take the marker now. The marker spends
        tokens like any other entry; when it does not fit it waits for the
        next tick — it never overshoots the bucket (the constructor guarantees
        the bucket can hold one marker, so it always fits eventually)."""
        if self._rate <= 0:
            return True
        return allowance >= marker_len

    async def _publish_marker(self, state, execution_id: str, cursor: int) -> bool:
        marker = self._marker()
        event = AgentLogEvent(
            agent_id=self._agent_id,
            task_id=state.task_id,
            execution_id=execution_id,
            offset=cursor,
            content_b64=base64.b64encode(marker).decode("ascii"),
            size_bytes=len(marker),
            eof=False,
            created_at=_now(),
        )
        try:
            await self._redis.xadd(
                LOG_STREAM, to_stream_entry(event),
                maxlen=self._maxlen, approximate=True,
            )
        except Exception as exc:  # noqa: BLE001 - retry next tick
            if self._status is not None:
                self._status.mark_error(exc)
            return False
        return True

    # --- publishing --------------------------------------------------------
    async def publish_attempt(self, execution_id: str) -> int:
        """Publish all currently-available bytes of one execution. Returns count.

        Honours the per-execution cap (publishes the truncation marker once,
        then stops tailing) and the agent-wide token bucket (publishes only as
        many bytes as the bucket allows; the rest waits for the next tick).
        """
        state = self._store.read(execution_id)
        if state is None or not state.log_path:
            return 0
        cursor = self._read_cursor(execution_id)
        total = 0
        if not state.log_capped:
            while True:
                allowance = self._allowance()
                if allowance <= 0:
                    break  # bucket dry: resume next tick
                if self._cap > 0 and cursor >= self._content_cap():
                    # Cap reached: one marker entry (it fits inside the cap),
                    # then never tail again. The marker is bucket-accounted
                    # like content: no allowance -> wait for the next tick.
                    marker_len = len(self._marker())
                    if not self._marker_allowed(allowance, marker_len):
                        break
                    if await self._publish_marker(state, execution_id, cursor):
                        state = self._store.mark_log_capped(execution_id) or state
                        self._spend(marker_len)
                        total += marker_len
                    break
                want = min(self._max_bytes, allowance)
                if self._cap > 0:
                    want = min(want, self._content_cap() - cursor)
                raw = self._read_raw(state.log_path, cursor, want)
                if not raw:
                    break
                event = AgentLogEvent(
                    agent_id=self._agent_id,
                    task_id=state.task_id,
                    execution_id=execution_id,
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
                except Exception as exc:  # noqa: BLE001 - leave cursor; retry next pass
                    if self._status is not None:
                        self._status.mark_error(exc)
                    logger.warning("log XADD failed for %s @ %d", execution_id, cursor)
                    return total
                if self._status is not None:
                    self._status.mark_log_publish()
                cursor += len(raw)
                self._write_cursor(execution_id, cursor)
                self._spend(len(raw))
                total += len(raw)
                if len(raw) < want:
                    break

        # terminal -> emit a single empty eof marker (optimization signal only).
        if state.phase == "done" and execution_id not in self._eof_sent:
            eof_event = AgentLogEvent(
                agent_id=self._agent_id,
                task_id=state.task_id,
                execution_id=execution_id,
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
                self._eof_sent.add(execution_id)
                if self._on_eof is not None:
                    # terminal + EOF published: release EOF-safe bookkeeping (C6).
                    try:
                        self._on_eof(execution_id)
                    except Exception:  # noqa: BLE001 - callback must not break publish
                        logger.warning(
                            "on_eof callback failed for %s", execution_id,
                            exc_info=True,
                        )
            except Exception as exc:  # noqa: BLE001
                if self._status is not None:
                    self._status.mark_error(exc)
                pass
        return total

    def forget(self, execution_id: str) -> None:
        """Drop per-execution cursor + EOF dedup state (resource caps, C1/C6).

        Called when the execution's state is removed (server ``cleanup_logs`` or
        the janitor TTL sweep). Deletes the ``.logpos`` cursor file — previously
        leaked one-per-execution forever — and clears the ``_eof_sent`` entry.
        Same lifetime as the scan source (the state file), so EOF stays idempotent
        until the execution truly goes away.
        """
        self._eof_sent.discard(execution_id)
        try:
            self._cursor_path(execution_id).unlink(missing_ok=True)
        except OSError:
            pass

    async def publish_once(self) -> int:
        """Publish increments for every execution that has local state.

        The scan starts where the previous tick stopped (rotation), so when the
        token bucket runs dry mid-scan the executions left behind go first next
        time instead of starving behind the same talkative ones.
        """
        self._refill()
        ids = sorted(self._store.list_execution_ids())
        if not ids:
            return 0
        start = self._rotate_from % len(ids)
        order = ids[start:] + ids[:start]
        total = 0
        for idx, execution_id in enumerate(order):
            if self._allowance() <= 0:
                self._rotate_from = (start + idx) % len(ids)
                break
            try:
                total += await self.publish_attempt(execution_id)
            except Exception:  # noqa: BLE001 - isolate one bad execution
                logger.warning("log publish failed for %s", execution_id, exc_info=True)
        else:
            self._rotate_from = 0
        return total

    # --- background loop ---------------------------------------------------
    async def _run(self) -> None:
        if self._status is not None:
            self._status.mark_log_running(True)
        try:
            while not self._stop.is_set():
                try:
                    await self.publish_once()
                except Exception as exc:  # noqa: BLE001 - never let the loop die
                    if self._status is not None:
                        self._status.mark_error(exc)
                    logger.warning("log publisher tick failed", exc_info=True)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
        finally:
            if self._status is not None:
                self._status.mark_log_running(False)

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
