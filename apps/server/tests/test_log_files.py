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
