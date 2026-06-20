"""Shared Scrapy command parser/validator (phase 1.8.1).

dopilot is **command-first**: an execution template (and a schedule override)
carries a single ``command`` string that is the authoritative execution input.
The ONLY supported grammar in this phase is::

    scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...

A command is NOT a shell command. It is tokenized (with quote support) and
interpreted by this explicit allowlist grammar — there is no shell execution,
no pipes/redirects/``;``/``&&``, no env prefixes, and no Scrapy subcommand other
than ``crawl``. This single parser is the authority shared by the **server**
(validates template/schedule input + re-validates at the dispatch boundary) and
the **agent** (parses the command into spider/args/settings before calling its
local scrapyd). The web mirrors the grammar for UX only; the backend remains
authoritative.

The parser is reject-by-default. ``shlex`` alone is not sufficient because shell
metacharacters tokenize as ordinary arguments, so unquoted metacharacters are
rejected up front and every token is then checked against the grammar.

This module is pure stdlib (``shlex`` + ``re``) so it can live in the shared,
dependency-light protocol package and be imported by both apps.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

# Shell metacharacters rejected when they appear OUTSIDE quotes. Quoted values
# may legitimately contain these (e.g. ``-a query="a&b"``); a bare occurrence is
# a shell-injection attempt and is refused. Backslash is rejected unquoted so the
# tokenizer's escape handling cannot be used to smuggle metacharacters.
_UNQUOTED_META = set(";&|<>`$(){}\\!*?[]#~\n\r")

# A spider name: starts alnum, then alnum / ``_`` / ``-`` / ``.``.
_SPIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# An ``-a`` / ``-s`` key: starts a letter or ``_``, then alnum / ``_`` / ``.`` / ``-``.
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

# Control characters are never allowed inside a value (even quoted).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ScrapyCommandError(ValueError):
    """A command failed allowlist validation.

    Carries a stable ``code`` / ``message_key`` (for the server's structured API
    error envelope and the web i18n) plus a ``reason`` and structured ``detail``
    the server/agent surface verbatim. The agent maps this onto a structured
    ``attempt.failed`` error.
    """

    code = "command.invalid"
    message_key = "errors.invalidCommand"

    def __init__(self, reason: str, detail: dict | None = None) -> None:
        self.reason = reason
        self.detail = {"reason": reason, **(detail or {})}
        super().__init__(f"invalid scrapy command: {reason}")


@dataclass(frozen=True)
class ParsedScrapyCommand:
    """The structured result of parsing a ``scrapy crawl`` command.

    ``spider`` is the spider name; ``args`` are the ``-a`` key/values (scrapy
    spider arguments); ``settings`` are the ``-s`` key/values (scrapy settings).
    Duplicate keys are last-write-wins.
    """

    spider: str
    args: dict[str, str] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)


def _reject_unquoted_metacharacters(command: str) -> None:
    """Refuse any shell metacharacter that appears outside a quoted span."""
    quote: str | None = None
    for ch in command:
        if quote is not None:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in _UNQUOTED_META:
            raise ScrapyCommandError("shell_metacharacter", {"char": ch})
    if quote is not None:
        raise ScrapyCommandError("unbalanced_quote")


def _tokenize(command: str) -> list[str]:
    _reject_unquoted_metacharacters(command)
    try:
        # posix=True so quotes are honored and stripped; whitespace-split.
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:  # unbalanced quote etc.
        raise ScrapyCommandError("unbalanced_quote", {"error": str(exc)}) from exc
    return tokens


def _validate_value(value: str) -> None:
    if _CONTROL_RE.search(value):
        raise ScrapyCommandError("invalid_value")


def parse_scrapy_command(command: str | None) -> ParsedScrapyCommand:
    """Parse + validate a ``scrapy crawl`` command, or raise ``ScrapyCommandError``.

    Accepts exactly ``scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...``.
    Quoted values are supported by the tokenizer; key/value split on the FIRST
    ``=`` (so ``=`` may appear in a value); empty values are allowed; duplicate
    keys are last-write-wins.
    """
    if not command or not command.strip():
        raise ScrapyCommandError("empty")

    tokens = _tokenize(command)
    if len(tokens) < 2 or tokens[0] != "scrapy" or tokens[1] != "crawl":
        raise ScrapyCommandError("not_scrapy_crawl")
    if len(tokens) < 3:
        raise ScrapyCommandError("missing_spider")

    spider = tokens[2]
    if spider.startswith("-") or not _SPIDER_RE.match(spider):
        raise ScrapyCommandError("missing_spider", {"spider": spider})

    args: dict[str, str] = {}
    settings: dict[str, str] = {}

    i = 3
    n = len(tokens)
    while i < n:
        flag = tokens[i]
        if flag == "-a":
            target = args
        elif flag == "-s":
            target = settings
        else:
            # Any other token: a second spider, an unsupported flag (``--set`` /
            # ``-o`` / ``-L`` …), or an attached ``-akey=value`` form.
            raise ScrapyCommandError("unsupported_flag", {"flag": flag})
        i += 1
        if i >= n:
            raise ScrapyCommandError("missing_value", {"flag": flag})
        pair = tokens[i]
        if "=" not in pair:
            raise ScrapyCommandError("malformed_pair", {"flag": flag, "pair": pair})
        key, _, value = pair.partition("=")
        if not key or not _KEY_RE.match(key):
            raise ScrapyCommandError("invalid_key", {"flag": flag, "key": key})
        _validate_value(value)
        target[key] = value  # last-write-wins on duplicate keys
        i += 1

    return ParsedScrapyCommand(spider=spider, args=args, settings=settings)


def is_valid_scrapy_command(command: str | None) -> bool:
    """``True`` iff :func:`parse_scrapy_command` accepts ``command``."""
    try:
        parse_scrapy_command(command)
    except ScrapyCommandError:
        return False
    return True


def _quote(value: str) -> str:
    """Quote a value for synthesis when it contains whitespace/metacharacters."""
    if value == "" or any(c.isspace() or c in _UNQUOTED_META for c in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def build_scrapy_command(
    spider: str,
    args: dict[str, str] | None = None,
    settings: dict[str, str] | None = None,
) -> str:
    """Synthesize a canonical command from decomposed spider/args/settings.

    The inverse of :func:`parse_scrapy_command`, used to best-effort migrate
    legacy decomposed templates into a single command string.
    """
    parts = ["scrapy", "crawl", spider]
    for key, value in (args or {}).items():
        parts.append("-a")
        parts.append(f"{key}={_quote(str(value))}")
    for key, value in (settings or {}).items():
        parts.append("-s")
        parts.append(f"{key}={_quote(str(value))}")
    return " ".join(parts)
