"""Parse the scrapy stats block from the tail of a job log (log-flood guard).

Scrapyd 1.x never exposes a crawler exit code, so a spider whose item pipeline
failed on every batch still ends ``finished``. The server's outcome judgement
therefore also looks at the crawler's own stats — ``'log_count/ERROR'`` and
``'finish_reason'`` — which scrapy dumps as a pretty-printed dict near the end
of the log (``[scrapy.statscollectors] INFO: Dumping Scrapy stats:``). This
module extracts those two values from the last bytes of the log; anything it
cannot find is ``None`` ("unknown"), never zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: How many bytes from the end of the log to scan for the stats block.
TAIL_BYTES = 65536

_RE_ERROR_COUNT = re.compile(rb"'log_count/ERROR':\s*(\d+)")
_RE_FINISH_REASON = re.compile(rb"'finish_reason':\s*'([^']+)'")
_STATS_BLOCK_MARKER = b"Dumping Scrapy stats"
# Lines of scrapy's pretty-printed stats dict: ``{'k': v,`` then `` 'k': v,``
# continuation lines; the last one ends with ``}``.
_RE_DICT_LINE = re.compile(rb"\A\s*[{']")


@dataclass(frozen=True)
class ScrapyStats:
    error_count: int | None
    finish_reason: str | None


def _last_stats_dict(tail: bytes) -> tuple[bytes, bool] | None:
    """Return ``(dict_text, closed)`` for the LAST ``Dumping Scrapy stats``
    block in ``tail`` — only the pretty-printed dict lines that follow the
    marker line — or ``None`` when there is no block at all. ``closed`` is
    False when the dict was cut off (log truncated mid-block)."""
    idx = tail.rfind(_STATS_BLOCK_MARKER)
    if idx < 0:
        return None
    nl = tail.find(b"\n", idx)
    if nl < 0:
        return b"", False
    lines: list[bytes] = []
    closed = False
    for line in tail[nl + 1 :].splitlines():
        if not _RE_DICT_LINE.match(line):
            break
        lines.append(line)
        if line.rstrip().endswith(b"}"):
            closed = True
            break
    return b"\n".join(lines), closed


def parse_scrapy_stats(tail: bytes) -> ScrapyStats:
    """Parse stats from ``tail`` (the last bytes of a job log).

    Only the LAST ``Dumping Scrapy stats`` block is consulted — never free-form
    log lines, so business output that happens to print ``finish_reason`` or
    ``log_count/ERROR`` can never fabricate stats. ``error_count`` is 0 when a
    complete block has no ``log_count/ERROR`` key (scrapy omits zero counters);
    it is ``None`` when no block exists at all (truncated log, crashed crawler,
    non-scrapy output) or when the block itself was cut off before that key.
    ``finish_reason`` is ``None`` when absent.
    """
    if not tail:
        return ScrapyStats(None, None)
    found = _last_stats_dict(tail)
    if found is None:
        return ScrapyStats(None, None)
    block, closed = found
    reason_m = _RE_FINISH_REASON.search(block)
    finish_reason = reason_m.group(1).decode("utf-8", errors="replace") if reason_m else None
    count_m = _RE_ERROR_COUNT.search(block)
    if count_m:
        error_count: int | None = int(count_m.group(1))
    elif closed:
        error_count = 0
    else:
        error_count = None
    return ScrapyStats(error_count=error_count, finish_reason=finish_reason)


def read_log_tail(path: str | Path, max_bytes: int = TAIL_BYTES) -> bytes:
    """Read the last ``max_bytes`` of ``path``; empty on any error."""
    try:
        p = Path(path)
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            return fh.read(max_bytes)
    except OSError:
        return b""


def log_size(path: str | Path) -> int | None:
    try:
        return Path(path).stat().st_size
    except OSError:
        return None
