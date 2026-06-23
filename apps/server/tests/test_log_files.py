"""Unit tests for the on-disk log store (offset math, tail, append)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dopilot_server.logs import files


def test_log_path_layout(tmp_path):
    when = datetime(2026, 6, 18, tzinfo=UTC)
    p = files.log_path(str(tmp_path), when, "exec1", "att1", "log")
    assert p.endswith("2026/06/exec1/att1.log")
    p2 = files.log_path(str(tmp_path), when, "exec1", "att1", "stdout")
    assert p2.endswith("2026/06/exec1/att1.stdout.log")


def test_size_missing_is_zero(tmp_path):
    assert files.size(str(tmp_path / "nope.log")) == 0


def test_append_and_read_slice(tmp_path):
    p = str(tmp_path / "a.log")
    assert files.append(p, b"hello ") == 6
    assert files.append(p, b"world") == 11
    start, end, text = files.read_slice(p, 0, 1024)
    assert (start, end, text) == (0, 11, "hello world")
    # slice from offset
    start, end, text = files.read_slice(p, 6, 1024)
    assert (start, end, text) == (6, 11, "world")


def test_read_slice_offset_past_eof_clamps(tmp_path):
    p = str(tmp_path / "a.log")
    files.append(p, b"abc")
    start, end, text = files.read_slice(p, 99, 10)
    assert (start, end, text) == (3, 3, "")


def test_read_slice_max_bytes_truncates(tmp_path):
    p = str(tmp_path / "a.log")
    files.append(p, b"abcdef")
    start, end, text = files.read_slice(p, 0, 3)
    assert (start, end, text) == (0, 3, "abc")


def test_read_slice_missing_file(tmp_path):
    start, end, text = files.read_slice(str(tmp_path / "no.log"), 5, 10)
    assert (start, end, text) == (5, 5, "")


def test_tail_screen_lines(tmp_path):
    p = str(tmp_path / "a.log")
    files.append(p, b"l1\nl2\nl3\nl4\n")
    start, end, text = files.tail_screen(p, max_lines=2, max_bytes=10_000)
    # last 2 lines region (the trailing newline makes "l4\n" + empty)
    assert "l4" in text and "l3" in text
    assert "l1" not in text
    assert end == files.size(p)


def test_tail_screen_bytes(tmp_path):
    p = str(tmp_path / "a.log")
    files.append(p, b"0123456789")
    start, end, text = files.tail_screen(p, max_lines=10_000, max_bytes=4)
    assert text == "6789"
    assert start == 6


def test_write_increment_idempotent_replay(tmp_path):
    p = str(tmp_path / "a.log")
    assert files.write_increment(p, 0, b"abc") == 3
    # replay same range -> no-op
    assert files.write_increment(p, 0, b"abc") == 3
    assert files.size(p) == 3
    # partial overlap appends only the new tail
    assert files.write_increment(p, 0, b"abcdef") == 6
    assert files.read_slice(p, 0, 99)[2] == "abcdef"


def test_write_increment_gap_raises(tmp_path):
    p = str(tmp_path / "a.log")
    files.append(p, b"ab")  # size 2
    with pytest.raises(files.LogGapError):
        files.write_increment(p, 5, b"xyz")  # resume offset beyond eof


# --- append_increment (collapsed marker+raw write) --------------------------


def test_append_increment_offsets_and_bytes(tmp_path):
    p = str(tmp_path / "a.log")
    # first write: no marker, raw only -> spans [0, 6)
    start, end = files.append_increment(p, b"", b"hello\n")
    assert (start, end) == (0, 6)
    assert files.size(p) == 6
    # second write with a gap marker prefixing the raw bytes
    marker = b"[gap]\n"
    start, end = files.append_increment(p, marker, b"world\n")
    assert start == 6
    assert end == 6 + len(marker) + len(b"world\n")
    assert end == files.size(p)
    assert files.read_slice(p, 0, 999)[2] == "hello\n[gap]\nworld\n"


def test_append_increment_empty_is_noop(tmp_path):
    p = str(tmp_path / "a.log")
    files.append(p, b"abc")
    start, end = files.append_increment(p, b"", b"")
    assert (start, end) == (3, 3)
    assert files.size(p) == 3


# --- async boundary: same semantics as the sync helpers ---------------------


async def test_async_helpers_match_sync(tmp_path):
    p = str(tmp_path / "a.log")
    # aappend_increment writes and returns physical offsets
    start, end = await files.aappend_increment(p, b"", b"hello world")
    assert (start, end) == (0, 11)
    assert await files.asize(p) == files.size(p) == 11
    # aread_slice mirrors read_slice
    assert await files.aread_slice(p, 0, 1024) == files.read_slice(p, 0, 1024)
    assert await files.aread_slice(p, 6, 1024) == files.read_slice(p, 6, 1024)
    # atail_screen mirrors tail_screen
    files.append(p, b"\nl2\nl3\n")
    assert await files.atail_screen(p, 2, 10_000) == files.tail_screen(
        p, 2, 10_000
    )


async def test_aremove_matches_remove(tmp_path):
    p = str(tmp_path / "sub" / "a.log")
    files.append(p, b"x")
    assert await files.aremove(p) is True
    assert files.size(p) == 0  # gone
    # second remove of a missing file is a best-effort False
    assert await files.aremove(p) is False
