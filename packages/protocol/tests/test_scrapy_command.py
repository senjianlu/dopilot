"""Unit tests for the shared Scrapy command parser/validator (phase 1.8.1)."""

from __future__ import annotations

import pytest
from dopilot_protocol import (
    ParsedScrapyCommand,
    ScrapyCommandError,
    ScrapyRunPayload,
    build_scrapy_command,
    is_valid_scrapy_command,
    parse_scrapy_command,
)

# --------------------------------------------------------------------------- #
# accepted forms
# --------------------------------------------------------------------------- #


def test_minimal_crawl():
    parsed = parse_scrapy_command("scrapy crawl phase1")
    assert parsed == ParsedScrapyCommand(spider="phase1", args={}, settings={})


def test_args_and_settings():
    parsed = parse_scrapy_command(
        "scrapy crawl phase1 -a page=1 -a tag=news -s LOG_LEVEL=DEBUG"
    )
    assert parsed.spider == "phase1"
    assert parsed.args == {"page": "1", "tag": "news"}
    assert parsed.settings == {"LOG_LEVEL": "DEBUG"}


def test_extra_whitespace_is_tolerated():
    parsed = parse_scrapy_command("  scrapy   crawl    phase1   -a k=v  ")
    assert parsed.spider == "phase1"
    assert parsed.args == {"k": "v"}


def test_spider_with_dots_dashes_underscores():
    parsed = parse_scrapy_command("scrapy crawl my.spider-name_2")
    assert parsed.spider == "my.spider-name_2"


# --------------------------------------------------------------------------- #
# quoting / value edge cases
# --------------------------------------------------------------------------- #


def test_quoted_value_with_spaces():
    parsed = parse_scrapy_command('scrapy crawl phase1 -a query="hello world"')
    assert parsed.args == {"query": "hello world"}


def test_single_quoted_value():
    parsed = parse_scrapy_command("scrapy crawl phase1 -a q='a b c'")
    assert parsed.args == {"q": "a b c"}


def test_equals_inside_value_splits_on_first():
    parsed = parse_scrapy_command("scrapy crawl phase1 -a expr=a=b=c")
    assert parsed.args == {"expr": "a=b=c"}


def test_empty_value_allowed():
    parsed = parse_scrapy_command("scrapy crawl phase1 -a flag=")
    assert parsed.args == {"flag": ""}


def test_duplicate_keys_last_write_wins():
    parsed = parse_scrapy_command("scrapy crawl phase1 -a page=1 -a page=2")
    assert parsed.args == {"page": "2"}


# --------------------------------------------------------------------------- #
# rejected forms
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command,reason",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("scrapy", "not_scrapy_crawl"),
        ("scrapy crawl", "missing_spider"),
        ("scrapy crawl -a k=v", "missing_spider"),
        ("scrapy list", "not_scrapy_crawl"),
        ("python crawl phase1", "not_scrapy_crawl"),
        ("scrapy crawl phase1 -o out.json", "unsupported_flag"),
        ("scrapy crawl phase1 --set FOO=bar", "unsupported_flag"),
        ("scrapy crawl phase1 -L DEBUG", "unsupported_flag"),
        ("scrapy crawl phase1 -akey=value", "unsupported_flag"),
        ("scrapy crawl phase1 -a", "missing_value"),
        ("scrapy crawl phase1 -a noequals", "malformed_pair"),
        ("scrapy crawl phase1 -a =novalue", "invalid_key"),
    ],
)
def test_rejected_grammar(command, reason):
    with pytest.raises(ScrapyCommandError) as exc:
        parse_scrapy_command(command)
    assert exc.value.reason == reason


@pytest.mark.parametrize(
    "command",
    [
        "scrapy crawl phase1; rm -rf /",
        "scrapy crawl phase1 && echo hi",
        "scrapy crawl phase1 | cat",
        "scrapy crawl phase1 > out.txt",
        "scrapy crawl phase1 `whoami`",
        "scrapy crawl phase1 $(whoami)",
        "scrapy crawl phase1 -a k=$HOME",
        "FOO=bar scrapy crawl phase1",
    ],
)
def test_rejects_shell_metacharacters(command):
    with pytest.raises(ScrapyCommandError):
        parse_scrapy_command(command)


def test_metacharacter_reason():
    with pytest.raises(ScrapyCommandError) as exc:
        parse_scrapy_command("scrapy crawl phase1; ls")
    assert exc.value.reason == "shell_metacharacter"
    assert exc.value.detail.get("char") == ";"


def test_unbalanced_quote_rejected():
    with pytest.raises(ScrapyCommandError) as exc:
        parse_scrapy_command('scrapy crawl phase1 -a k="open')
    assert exc.value.reason == "unbalanced_quote"


def test_quoted_metacharacter_allowed_in_value():
    # A metacharacter INSIDE quotes is a literal value, not shell syntax.
    parsed = parse_scrapy_command('scrapy crawl phase1 -a q="a&b|c"')
    assert parsed.args == {"q": "a&b|c"}


def test_error_envelope_fields():
    err = ScrapyCommandError("missing_spider", {"spider": "-x"})
    assert err.code == "command.invalid"
    assert err.message_key == "errors.invalidCommand"
    assert err.detail == {"reason": "missing_spider", "spider": "-x"}


def test_is_valid_helper():
    assert is_valid_scrapy_command("scrapy crawl phase1")
    assert not is_valid_scrapy_command("rm -rf /")


# --------------------------------------------------------------------------- #
# synthesis (migration helper) round-trips
# --------------------------------------------------------------------------- #


def test_build_command_roundtrips():
    command = build_scrapy_command(
        "phase1", {"page": "1"}, {"LOG_LEVEL": "DEBUG"}
    )
    parsed = parse_scrapy_command(command)
    assert parsed.spider == "phase1"
    assert parsed.args == {"page": "1"}
    assert parsed.settings == {"LOG_LEVEL": "DEBUG"}


def test_build_command_quotes_spaces_and_roundtrips():
    command = build_scrapy_command("phase1", {"q": "hello world"})
    parsed = parse_scrapy_command(command)
    assert parsed.args == {"q": "hello world"}


# --------------------------------------------------------------------------- #
# run payload schema round-trips
# --------------------------------------------------------------------------- #


def test_run_payload_roundtrips():
    payload = ScrapyRunPayload(
        command="scrapy crawl phase1 -s LOG_LEVEL=DEBUG",
        artifact={"project": "demo", "version": "v1", "sha256": "a" * 64},
    )
    restored = ScrapyRunPayload.model_validate(payload.model_dump())
    assert restored.command == payload.command
    assert restored.artifact["project"] == "demo"
    assert restored.task_type == "scrapy"
