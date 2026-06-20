"""On-disk log body store.

Bodies live at ``{root}/YYYY/MM/{execution_id}/{attempt_id}.log`` (stream=log)
or ``{attempt_id}.{stream}.log`` for other streams. PostgreSQL stores only the
offset/index; this module is the body side.

Writes are append-only and offset-idempotent: :func:`write_increment` is safe to
replay (server may re-pull the same byte range if a DB commit was lost). If the
file is shorter than the offset we are resuming from (truncated/lost), it raises
:class:`LogGapError` so the caller can mark the log ``missing``.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


class LogGapError(Exception):
    """The on-disk file is shorter than the offset being resumed from."""


def log_path(
    root_dir: str,
    when: datetime,
    execution_id: str,
    attempt_id: str,
    stream: str = "log",
) -> str:
    """Compute the body path for one attempt+stream (stable for an execution)."""
    name = f"{attempt_id}.log" if stream == "log" else f"{attempt_id}.{stream}.log"
    return str(
        Path(root_dir)
        / f"{when.year:04d}"
        / f"{when.month:02d}"
        / execution_id
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
    the file, the now-possibly-empty per-execution parent directory is pruned
    (also best-effort) so manual cleanup does not leave empty ``{execution_id}/``
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
