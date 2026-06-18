"""Regression: agent tail must not corrupt multi-byte UTF-8 at a pull boundary.

A multibyte char split across the max_bytes boundary (read stops before EOF)
must be trimmed off end_offset so the next pull re-reads it on a char boundary,
instead of being permanently replaced with U+FFFD and skipped.
"""

from __future__ import annotations

from dopilot_agent.logs.tail import tail_file


def test_trims_partial_utf8_before_eof(tmp_path):
    p = tmp_path / "job.log"
    p.write_bytes("中中".encode())  # 6 bytes (3 + 3)

    # Read 4 bytes: one full char (3) + 1 partial byte of the second char.
    res = tail_file(str(p), 0, 4)
    assert res.content == "中"
    assert res.end_offset == 3  # trimmed back to the char boundary, not 4
    assert res.eof is False

    # Next pull resumes exactly where the char begins.
    res2 = tail_file(str(p), res.end_offset, 4)
    assert res2.content == "中"
    assert res2.end_offset == 6
    assert res2.eof is True


def test_keeps_replacement_at_true_eof(tmp_path):
    p = tmp_path / "job.log"
    p.write_bytes(b"\xe4\xb8")  # an incomplete 3-byte char that is the whole file
    res = tail_file(str(p), 0, 16)
    # At genuine EOF we tolerate the partial char (replace) and advance to size.
    assert res.eof is True
    assert res.end_offset == 2


def test_no_stall_when_max_bytes_smaller_than_char(tmp_path):
    p = tmp_path / "job.log"
    p.write_bytes("中".encode())  # 3 bytes
    # max_bytes=2 < 3: trimming to a boundary would be empty -> must still make
    # forward progress (accept a replacement) rather than return 0 bytes.
    res = tail_file(str(p), 0, 2)
    assert res.end_offset == 2
