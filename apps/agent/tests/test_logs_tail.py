"""Unit tests for the byte-offset file tail."""

from __future__ import annotations

from pathlib import Path

from dopilot_agent.logs.tail import tail_file


def _write(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "job.log"
    p.write_bytes(data)
    return p


def test_empty_file(tmp_path: Path) -> None:
    p = _write(tmp_path, b"")
    r = tail_file(p, 0, 1024)
    assert r.start_offset == 0
    assert r.end_offset == 0
    assert r.content == ""
    assert r.eof is True


def test_full_read_from_zero(tmp_path: Path) -> None:
    p = _write(tmp_path, b"hello world")
    r = tail_file(p, 0, 1024)
    assert r.start_offset == 0
    assert r.end_offset == 11
    assert r.content == "hello world"
    assert r.eof is True


def test_append_continues_from_offset(tmp_path: Path) -> None:
    p = _write(tmp_path, b"hello")
    r1 = tail_file(p, 0, 1024)
    assert r1.end_offset == 5
    # Append.
    with p.open("ab") as fh:
        fh.write(b" world")
    r2 = tail_file(p, r1.end_offset, 1024)
    assert r2.start_offset == 5
    assert r2.end_offset == 11
    assert r2.content == " world"
    assert r2.eof is True


def test_offset_equals_size_clamps(tmp_path: Path) -> None:
    p = _write(tmp_path, b"hello")
    r = tail_file(p, 5, 1024)
    assert r.start_offset == 5
    assert r.end_offset == 5
    assert r.content == ""
    assert r.eof is True


def test_offset_greater_than_size_clamps_to_size(tmp_path: Path) -> None:
    p = _write(tmp_path, b"hello")
    r = tail_file(p, 999, 1024)
    assert r.start_offset == 5
    assert r.end_offset == 5
    assert r.content == ""
    assert r.eof is True


def test_max_bytes_truncation_reports_not_eof(tmp_path: Path) -> None:
    p = _write(tmp_path, b"abcdefghij")  # 10 bytes
    r = tail_file(p, 0, 4)
    assert r.start_offset == 0
    assert r.end_offset == 4
    assert r.content == "abcd"
    assert r.eof is False
    # Next pull picks up where we left off.
    r2 = tail_file(p, r.end_offset, 4)
    assert r2.content == "efgh"
    assert r2.eof is False


def test_missing_file(tmp_path: Path) -> None:
    r = tail_file(tmp_path / "nope.log", 0, 1024)
    assert r.start_offset == 0
    assert r.end_offset == 0
    assert r.content == ""
    assert r.eof is True


def test_utf8_replace_on_split_multibyte(tmp_path: Path) -> None:
    # "é" is two bytes (0xC3 0xA9). Reading only the first byte must not raise.
    p = _write(tmp_path, "é".encode())
    r = tail_file(p, 0, 1)
    assert r.start_offset == 0
    assert r.end_offset == 1
    assert r.content == "�"  # replacement char
    assert r.eof is False
