"""Byte-offset file tail.

:func:`tail_file` is the pure, side-effect-free core of ``GET /logs/tail``: it
reads a byte slice ``[offset, offset+max_bytes)`` of a log file and reports
where the read started/ended and whether it reached EOF. Offset authority lives
on the server (PostgreSQL ``execution_log_files.last_pulled_offset``); the agent
is stateless and only answers "give me bytes from here".

Semantics (mirrors the protocol ``TailResponse``):
- normal read: ``start=offset``, ``end=offset+len(read)``, ``eof = end>=size``;
- ``offset >= size`` (caller already past EOF): clamp to ``start=end=size`` with
  empty content and ``eof=True`` — never seek past the file or raise;
- missing file: ``start=end=0``, empty content, ``eof=True`` (the caller layers
  the attempt's terminal status on top to decide ``finished``).

A multibyte UTF-8 sequence split across a ``max_bytes`` boundary is NOT decoded
to U+FFFD and consumed: when the read stops before real EOF, the trailing
partial bytes are trimmed off ``end_offset`` so the next pull re-reads them on a
character boundary (no permanent on-disk corruption). ``errors="replace"`` is
kept only for the genuine end-of-file case (and truly invalid mid-stream bytes).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _strip_incomplete_utf8_tail(chunk: bytes) -> bytes:
    """Return the longest prefix of ``chunk`` that is valid UTF-8.

    Only the last <=3 bytes of a UTF-8 stream can be an incomplete trailing
    sequence, so try the full length then back off up to 3 bytes. If even the
    full chunk fails (genuinely invalid mid-stream bytes), give up and return it
    unchanged (the caller decodes with ``errors="replace"``).
    """
    for back in range(0, min(3, len(chunk)) + 1):
        cut = len(chunk) - back
        try:
            chunk[:cut].decode("utf-8")
            return chunk[:cut]
        except UnicodeDecodeError:
            continue
    return chunk


@dataclass(frozen=True)
class TailResult:
    """Result of a byte-offset tail read."""

    start_offset: int
    end_offset: int
    content: str
    eof: bool


def tail_file(
    path: str | Path, offset: int, max_bytes: int
) -> TailResult:
    """Read up to ``max_bytes`` bytes of ``path`` starting at ``offset``."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except (FileNotFoundError, NotADirectoryError):
        return TailResult(start_offset=0, end_offset=0, content="", eof=True)

    start = max(0, offset)
    if start >= size:
        # Caller is at or past EOF: clamp, return nothing.
        return TailResult(start_offset=size, end_offset=size, content="", eof=True)

    read_n = max(0, max_bytes)
    with p.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read(read_n)

    end = start + len(chunk)
    # If we stopped before real EOF, drop a trailing partial UTF-8 sequence so
    # the next pull resumes on a character boundary. Never trim to empty (that
    # would stall progress when max_bytes is smaller than one char's bytes).
    if end < size and chunk:
        trimmed = _strip_incomplete_utf8_tail(chunk)
        if trimmed:
            chunk = trimmed
            end = start + len(chunk)
    content = chunk.decode("utf-8", errors="replace")
    return TailResult(
        start_offset=start,
        end_offset=end,
        content=content,
        eof=end >= size,
    )
