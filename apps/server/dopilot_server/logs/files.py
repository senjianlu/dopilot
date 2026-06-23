"""On-disk log body store.

Bodies live at ``{root}/YYYY/MM/{task_id}/{execution_id}.log`` (stream=log)
or ``{execution_id}.{stream}.log`` for other streams. PostgreSQL stores only the
offset/index; this module is the body side.

Writes are append-only and offset-idempotent: :func:`write_increment` is safe to
replay (server may re-pull the same byte range if a DB commit was lost). If the
file is shorter than the offset we are resuming from (truncated/lost), it raises
:class:`LogGapError` so the caller can mark the log ``missing``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path


class LogGapError(Exception):
    """The on-disk file is shorter than the offset being resumed from."""


def log_path(
    root_dir: str,
    when: datetime,
    task_id: str,
    execution_id: str,
    stream: str = "log",
) -> str:
    """Compute the body path for one execution+stream (stable for an execution)."""
    name = (
        f"{execution_id}.log"
        if stream == "log"
        else f"{execution_id}.{stream}.log"
    )
    return str(
        Path(root_dir)
        / f"{when.year:04d}"
        / f"{when.month:02d}"
        / task_id
        / name
    )


def size(path: str) -> int:
    """Current file size in bytes (0 if the file does not exist)."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def write_increment(path: str, start_offset: int, data: bytes) -> int:
    """Append ``data`` (the slice that begins at ``start_offset``) idempotently.

    Returns the new file size. Replaying an already-written range is a no-op.
    Raises :class:`LogGapError` if the file is shorter than ``start_offset``.
    """
    if not data:
        return size(path)
    cur = size(path)
    end = start_offset + len(data)
    if cur >= end:
        return cur  # already written (lost-DB-commit replay)
    if cur < start_offset:
        raise LogGapError(
            f"file {path} size {cur} < resume offset {start_offset}"
        )
    skip = cur - start_offset
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as fh:
        fh.write(data[skip:])
    return start_offset + len(data)


def append(path: str, data: bytes) -> int:
    """Append ``data`` to the end of the server-side body file; return new size.

    The server file uses its OWN byte-offset space (used for SSE event ids and
    snapshot reads). The agent's byte offset (``last_pulled_offset``) is tracked
    separately because the agent returns decoded text (utf-8 ``replace``) whose
    re-encoded length need not equal the agent's raw byte range.
    """
    if not data:
        return size(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as fh:
        fh.write(data)
    return size(path)


def remove(path: str) -> bool:
    """Delete one log body file; return True if a file was removed.

    Best-effort: a missing file is not an error (returns False). After removing
    the file, the now-possibly-empty per-task parent directory is pruned
    (also best-effort) so manual cleanup does not leave empty ``{task_id}/``
    shells behind. Higher directories (YYYY/MM) are left intact.
    """
    removed = False
    try:
        os.remove(path)
        removed = True
    except OSError:
        return False
    try:
        os.rmdir(Path(path).parent)
    except OSError:
        pass  # directory not empty / already gone — leave it.
    return removed


def read_slice(path: str, offset: int, max_bytes: int) -> tuple[int, int, str]:
    """Read up to ``max_bytes`` from ``offset``.

    Returns ``(start_offset, end_offset, text)``. ``offset`` past EOF clamps to
    file size with empty content. Missing file yields ``(offset, offset, "")``.
    """
    fsize = size(path)
    if fsize == 0 and not Path(path).exists():
        return offset, offset, ""
    start = min(max(offset, 0), fsize)
    with open(path, "rb") as fh:
        fh.seek(start)
        chunk = fh.read(max(0, max_bytes))
    end = start + len(chunk)
    return start, end, chunk.decode("utf-8", errors="replace")


def tail_screen(
    path: str, max_lines: int, max_bytes: int
) -> tuple[int, int, str]:
    """Return the last ``max_lines`` lines OR last ``max_bytes`` bytes.

    Whichever boundary is hit first (i.e. the larger start offset). Returns
    ``(start_offset, end_offset, text)`` so the caller can seed the SSE
    ``Last-Event-ID`` baseline at ``end_offset``.
    """
    fsize = size(path)
    if fsize == 0:
        return 0, 0, ""
    byte_start = max(0, fsize - max(0, max_bytes))
    with open(path, "rb") as fh:
        fh.seek(byte_start)
        chunk = fh.read()
    # Trim to the last max_lines lines within the byte window. A trailing
    # newline produces a final empty element that must not consume a line slot.
    if max_lines > 0:
        lines = chunk.split(b"\n")
        trailing_nl = bool(lines) and lines[-1] == b""
        body = lines[:-1] if trailing_nl else lines
        if len(body) > max_lines:
            trimmed = b"\n".join(body[-max_lines:])
            if trailing_nl:
                trimmed += b"\n"
            byte_start = fsize - len(trimmed)
            chunk = trimmed
    return byte_start, fsize, chunk.decode("utf-8", errors="replace")


def append_increment(path: str, marker: bytes, raw: bytes) -> tuple[int, int]:
    """Append an optional gap ``marker`` then ``raw`` in ONE file open.

    Returns ``(physical_start, physical_end)``: the server-file byte offsets that
    span exactly the bytes just written (``marker + raw``). These are the offsets
    the log consumer needs for the DB index (``size_bytes`` / ``final_offset``)
    and the SSE ``start_offset`` / ``end_offset``.

    Single-writer invariant: this read-size-then-append is race-free ONLY because
    the Redis :class:`~dopilot_server.redis.consumers.LogConsumer` is the sole
    writer and applies events serially (``_apply_one`` is awaited one at a time);
    snapshot/SSE paths only read, and ``write_increment`` has no live caller. Do
    NOT introduce a second concurrent writer to the same body file without adding
    a lock — the size/append split would then drop or overlap bytes.
    """
    physical_start = size(path)
    if marker or raw:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as fh:
            if marker:
                fh.write(marker)
            if raw:
                fh.write(raw)
    physical_end = physical_start + len(marker) + len(raw)
    return physical_start, physical_end


# --- async boundary -------------------------------------------------------
#
# Named async wrappers so callers on the single ``dopilot-server`` asyncio event
# loop (request handlers, the Redis log consumer, the SSE generator, maintenance)
# never run the blocking ``open``/``read``/``write``/``getsize``/``remove``
# syscalls or the UTF-8 decode directly on the loop. Each offloads the matching
# synchronous helper above to the default thread executor via
# :func:`asyncio.to_thread`. The synchronous helpers stay public for unit tests
# and any non-async use; the async variants are the boundary async code must use.


async def asize(path: str) -> int:
    """Async :func:`size` (offloaded to a thread)."""
    return await asyncio.to_thread(size, path)


async def aread_slice(
    path: str, offset: int, max_bytes: int
) -> tuple[int, int, str]:
    """Async :func:`read_slice` (offloaded to a thread)."""
    return await asyncio.to_thread(read_slice, path, offset, max_bytes)


async def atail_screen(
    path: str, max_lines: int, max_bytes: int
) -> tuple[int, int, str]:
    """Async :func:`tail_screen` (offloaded to a thread)."""
    return await asyncio.to_thread(tail_screen, path, max_lines, max_bytes)


async def aremove(path: str) -> bool:
    """Async :func:`remove` (offloaded to a thread)."""
    return await asyncio.to_thread(remove, path)


async def aappend_increment(
    path: str, marker: bytes, raw: bytes
) -> tuple[int, int]:
    """Async :func:`append_increment`: marker+raw append + offsets in ONE hop."""
    return await asyncio.to_thread(append_increment, path, marker, raw)
