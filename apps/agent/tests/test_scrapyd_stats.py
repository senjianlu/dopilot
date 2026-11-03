"""TC-05: scrapy stats parsing from the job log tail (log-flood guard)."""

from __future__ import annotations

from pathlib import Path

from dopilot_agent.scrapyd.stats import (
    TAIL_BYTES,
    log_size,
    parse_scrapy_stats,
    read_log_tail,
)

STATS_TAIL = b"""\
2026-08-21 11:30:27 [scrapy.core.scraper] ERROR: Error processing {'app_id': 'g1'}
2026-08-21 12:10:01 [scrapy.statscollectors] INFO: Dumping Scrapy stats:
{'downloader/request_count': 1337,
 'elapsed_time_seconds': 2395.2,
 'finish_reason': 'finished',
 'finish_time': datetime.datetime(2026, 8, 21, 12, 10, 1, tzinfo=datetime.timezone.utc),
 'log_count/ERROR': 91,
 'log_count/INFO': 57,
 'log_count/WARNING': 5}
2026-08-21 12:10:01 [scrapy.core.engine] INFO: Spider closed (finished)
"""


def test_parses_error_count_and_finish_reason() -> None:
    stats = parse_scrapy_stats(STATS_TAIL)
    assert stats.error_count == 91
    assert stats.finish_reason == "finished"


def test_truncated_log_without_stats_block_is_unknown() -> None:
    truncated = (
        b"INSERT INTO prices (...) VALUES (...)\n"
        b"[dopilot:log-truncated max_bytes=1 reason=size-cap]\n"
    )
    stats = parse_scrapy_stats(truncated)
    assert stats.error_count is None
    assert stats.finish_reason is None
    assert parse_scrapy_stats(b"") == parse_scrapy_stats(truncated)


def test_stats_block_without_error_key_means_zero_errors() -> None:
    tail = b"""\
[scrapy.statscollectors] INFO: Dumping Scrapy stats:
{'downloader/request_count': 3,
 'finish_reason': 'closespider_errorcount',
 'log_count/INFO': 10}
"""
    stats = parse_scrapy_stats(tail)
    assert stats.error_count == 0
    assert stats.finish_reason == "closespider_errorcount"


def test_last_stats_block_wins_when_log_has_several() -> None:
    tail = (
        b"{'finish_reason': 'shutdown', 'log_count/ERROR': 3}\n"
        b"Dumping Scrapy stats:\n{'finish_reason': 'finished', 'log_count/ERROR': 5}\n"
    )
    stats = parse_scrapy_stats(tail)
    assert (stats.error_count, stats.finish_reason) == (5, "finished")


def test_read_log_tail_reads_only_last_bytes(tmp_path: Path) -> None:
    p = tmp_path / "job.log"
    p.write_bytes(b"x" * (TAIL_BYTES + 100) + STATS_TAIL)
    tail = read_log_tail(p)
    assert len(tail) == TAIL_BYTES
    assert tail.endswith(STATS_TAIL)
    assert parse_scrapy_stats(tail).error_count == 91
    assert log_size(p) == TAIL_BYTES + 100 + len(STATS_TAIL)
    assert read_log_tail(tmp_path / "missing.log") == b""
    assert log_size(tmp_path / "missing.log") is None


# --- round 5 R-01: only the stats BLOCK is consulted, never free-form log lines -------


def test_business_log_lines_without_stats_block_never_fabricate_stats() -> None:
    tail = (
        b"INFO: saved row {'finish_reason': 'finished', 'log_count/ERROR': 0}\n"
        b"INFO: item {'id': 1, 'finish_reason': 'finished'}\n"
        b"ERROR: 'log_count/ERROR': 17 printed by the spider itself\n"
    )
    assert parse_scrapy_stats(tail) == parse_scrapy_stats(b"")  # (None, None)


def test_lines_after_the_stats_block_are_ignored() -> None:
    tail = (
        b"[scrapy.statscollectors] INFO: Dumping Scrapy stats:\n"
        b"{'finish_reason': 'finished',\n"
        b" 'log_count/INFO': 10}\n"
        b"[scrapy.core.engine] INFO: Spider closed (finished)\n"
        b"INFO: audit {'finish_reason': 'shutdown', 'log_count/ERROR': 999}\n"
    )
    stats = parse_scrapy_stats(tail)
    assert (stats.error_count, stats.finish_reason) == (0, "finished")


def test_stats_block_cut_off_before_error_key_is_unknown_not_zero() -> None:
    tail = (
        b"[scrapy.statscollectors] INFO: Dumping Scrapy stats:\n"
        b"{'downloader/request_count': 3,\n"
        b" 'finish_reason': 'finished',\n"
        b"\n[dopilot:log-truncated max_bytes=1 reason=size-cap]\n"
    )
    stats = parse_scrapy_stats(tail)
    assert stats.error_count is None
    assert stats.finish_reason == "finished"


# --- schedule circuit breaker (decision 0025): ``'outcome/class'`` -------------------


def test_outcome_class_is_read_from_the_last_stats_block() -> None:
    tail = (
        b"[scrapy.statscollectors] INFO: Dumping Scrapy stats:\n"
        b"{'finish_reason': 'site_request_failed',\n"
        b" 'log_count/ERROR': 2,\n"
        b" 'outcome/class': 'transient'}\n"
    )
    stats = parse_scrapy_stats(tail)
    assert stats.outcome_class == "transient"
    # the two pre-existing keys are parsed exactly as before
    assert (stats.error_count, stats.finish_reason) == (2, "site_request_failed")


def test_outcome_class_absent_from_last_block_is_none() -> None:
    assert parse_scrapy_stats(STATS_TAIL).outcome_class is None
    assert parse_scrapy_stats(b"").outcome_class is None


def test_outcome_class_only_in_an_earlier_block_is_ignored() -> None:
    tail = (
        b"Dumping Scrapy stats:\n{'finish_reason': 'shutdown', 'outcome/class': 'transient'}\n"
        b"Dumping Scrapy stats:\n{'finish_reason': 'finished', 'log_count/ERROR': 1}\n"
    )
    stats = parse_scrapy_stats(tail)
    assert stats.outcome_class is None
    assert (stats.error_count, stats.finish_reason) == (1, "finished")


def test_outcome_class_in_business_log_lines_is_never_trusted() -> None:
    tail = (
        b"INFO: audit {'outcome/class': 'transient'}\n"
        b"[scrapy.statscollectors] INFO: Dumping Scrapy stats:\n"
        b"{'finish_reason': 'finished',\n 'log_count/ERROR': 4}\n"
        b"INFO: after {'outcome/class': 'transient'}\n"
    )
    stats = parse_scrapy_stats(tail)
    assert stats.outcome_class is None
    assert (stats.error_count, stats.finish_reason) == (4, "finished")


def test_outcome_class_is_truncated_to_64_chars() -> None:
    long_value = "t" * 200
    tail = (
        b"Dumping Scrapy stats:\n{'finish_reason': 'finished', 'outcome/class': '"
        + long_value.encode()
        + b"'}\n"
    )
    stats = parse_scrapy_stats(tail)
    assert stats.outcome_class == "t" * 64


def test_outcome_class_with_invalid_utf8_does_not_raise() -> None:
    tail = b"Dumping Scrapy stats:\n{'finish_reason': 'finished', 'outcome/class': 'tr\xff\xfe'}\n"
    stats = parse_scrapy_stats(tail)
    assert stats.outcome_class is not None and stats.outcome_class.startswith("tr")
    assert stats.finish_reason == "finished"
