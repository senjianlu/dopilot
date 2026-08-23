"""In-process job-log size cap for scrapyd crawler processes (log-flood guard).

Imported at interpreter startup by ``dopilot_logcap.pth`` (installed at the
site-packages root by the agent wheel) in EVERY Python process of the scrapyd
environment. It is a strict no-op unless ``sys.argv`` identifies a scrapyd
crawler job — so the scrapyd daemon, the agent itself and any unrelated
process are never patched. A crawler is recognised only when argv carries all
of:

- ``crawl`` (the scrapyd runner subcommand),
- an ``_job=<id>`` argument (scrapyd's per-job spider argument),
- ``-s DOPILOT_JOB_LOG_CAP_BYTES=<n>`` with ``n > 0`` (injected by the agent's
  scrapy runner into the ``schedule.json`` ``setting`` list, which scrapyd
  forwards verbatim as ``-s key=value``),
- ``-s LOG_FILE=<path>`` (scrapyd's per-job log path).

When active, the hook patches :class:`logging.FileHandler` so that ONLY the
handler instance writing to that ``LOG_FILE`` is capped: once its written bytes
reach the cap it writes one truncation marker, drops every further record and
sends a single ``SIGTERM`` to its own process (scrapy handles it as a graceful
shutdown, ``finish_reason=shutdown``). The provable upper bound on the file is
therefore ``cap + one record + marker`` and it does not depend on any polling
by the agent. Environment variables are deliberately NOT an activation source.

Only the standard library is imported here: this module must stay cheap and
side-effect free for every non-crawler process.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from typing import Any

SETTING_NAME = "DOPILOT_JOB_LOG_CAP_BYTES"
LOG_FILE_SETTING = "LOG_FILE"

_state: dict[str, Any] = {
    "installed": False,
    "cap": 0,
    "log_file": "",
    "orig_init": None,
    "orig_emit": None,
}


def truncation_marker(cap: int) -> str:
    return f"\n[dopilot:job-log-truncated max_bytes={cap} reason=size-cap]\n"


def parse_crawler_argv(argv: list[str]) -> tuple[int, str] | None:
    """Return ``(cap, log_file)`` iff ``argv`` is a scrapyd crawler with a cap."""
    if "crawl" not in argv:
        return None
    if not any("_job=" in a for a in argv):
        return None
    settings: dict[str, str] = {}
    for i, tok in enumerate(argv):
        if tok == "-s" and i + 1 < len(argv) and "=" in argv[i + 1]:
            key, _, val = argv[i + 1].partition("=")
            settings[key] = val
        elif tok.startswith("-s") and "=" in tok and tok != "-s":
            key, _, val = tok[2:].partition("=")
            settings[key] = val
    raw = settings.get(SETTING_NAME)
    log_file = settings.get(LOG_FILE_SETTING)
    if not raw or not log_file:
        return None
    try:
        cap = int(raw)
    except ValueError:
        return None
    if cap <= 0:
        return None
    return cap, log_file


def _same_file(a: str, b: str) -> bool:
    return os.path.abspath(a) == os.path.abspath(b)


def _patched_init(self: logging.FileHandler, *args: Any, **kwargs: Any) -> None:
    _state["orig_init"](self, *args, **kwargs)
    base = getattr(self, "baseFilename", None)
    if base and _same_file(base, _state["log_file"]):
        self._dopilot_cap = _state["cap"]  # type: ignore[attr-defined]
        try:
            existing = os.path.getsize(base)
        except OSError:
            existing = 0
        self._dopilot_written = existing  # type: ignore[attr-defined]
        self._dopilot_capped = False  # type: ignore[attr-defined]


def _patched_emit(self: logging.FileHandler, record: logging.LogRecord) -> None:
    cap = getattr(self, "_dopilot_cap", None)
    if cap is None:
        _state["orig_emit"](self, record)
        return
    if self._dopilot_capped:  # type: ignore[attr-defined]
        return
    try:
        rendered = self.format(record) + self.terminator
        size = len(rendered.encode(self.encoding or "utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - never break logging on a bad record
        size = 0
    _state["orig_emit"](self, record)
    self._dopilot_written += size  # type: ignore[attr-defined]
    if self._dopilot_written < cap:  # type: ignore[attr-defined]
        return
    # Cap reached: one marker, then drop everything, then ask scrapy to stop.
    self._dopilot_capped = True  # type: ignore[attr-defined]
    try:
        stream = self.stream
        if stream is not None:
            stream.write(truncation_marker(cap))
            stream.flush()
    except Exception:  # noqa: BLE001
        pass
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        pass


def install(argv: list[str] | None = None) -> bool:
    """Activate the cap iff ``argv`` (default ``sys.argv``) is a crawler job.

    Idempotent; returns True when the patch is (already) active.
    """
    if _state["installed"]:
        return True
    parsed = parse_crawler_argv(list(sys.argv if argv is None else argv))
    if parsed is None:
        return False
    cap, log_file = parsed
    _state.update(
        installed=True,
        cap=cap,
        log_file=log_file,
        orig_init=logging.FileHandler.__init__,
        orig_emit=logging.FileHandler.emit,
    )
    logging.FileHandler.__init__ = _patched_init  # type: ignore[method-assign]
    logging.FileHandler.emit = _patched_emit  # type: ignore[method-assign]
    return True


def uninstall() -> None:
    """Restore ``logging.FileHandler`` (tests only)."""
    if not _state["installed"]:
        return
    logging.FileHandler.__init__ = _state["orig_init"]  # type: ignore[method-assign]
    logging.FileHandler.emit = _state["orig_emit"]  # type: ignore[method-assign]
    _state.update(installed=False, cap=0, log_file="", orig_init=None, orig_emit=None)


def is_installed() -> bool:
    return bool(_state["installed"])


# ``.pth`` entry point: decide once, at interpreter startup, from the real argv.
install()
