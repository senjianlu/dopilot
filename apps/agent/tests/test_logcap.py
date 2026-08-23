"""TC-01d / TC-01e / TC-01g: the in-process crawler log cap (``logcap``)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from dopilot_agent import logcap


@pytest.fixture(autouse=True)
def _restore_logcap():
    logcap.uninstall()
    yield
    logcap.uninstall()


def _crawler_argv(log_file: Path, cap: int) -> list[str]:
    # The exact shape scrapyd's launcher hands a crawler: ``python -m
    # scrapyd.runner crawl <spider> -a _job=<id> -s LOG_FILE=<p> -s ...``.
    return [
        "/usr/local/lib/python3.12/site-packages/scrapyd/runner.py",
        "crawl",
        "steammarket",
        "-a",
        "_job=abc123",
        "-s",
        f"LOG_FILE={log_file}",
        "-s",
        f"{logcap.SETTING_NAME}={cap}",
    ]


def _make_handler(path: Path) -> logging.FileHandler:
    handler = logging.FileHandler(str(path), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def _emit(handler: logging.Handler, size: int, count: int) -> None:
    logger = logging.getLogger(f"logcap-test-{id(handler)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    payload = "x" * (size - 1)
    for _ in range(count):
        logger.info(payload)


# --- TC-01d -------------------------------------------------------------------


def test_caps_only_the_log_file_handler_and_sigterms_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "job.log"
    other = tmp_path / "other.log"
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))

    assert logcap.install(_crawler_argv(log_file, 4096)) is True
    assert logcap.is_installed()

    capped = _make_handler(log_file)
    free = _make_handler(other)
    record = 10 * 1024
    _emit(capped, record, 5000)
    _emit(free, record, 5000)
    capped.close()
    free.close()

    marker = logcap.truncation_marker(4096)
    size = log_file.stat().st_size
    assert size <= 4096 + record + len(marker)
    assert log_file.read_text(encoding="utf-8").count("[dopilot:job-log-truncated") == 1
    assert kills == [(os.getpid(), signal.SIGTERM)]
    # The other FileHandler in the same process is untouched.
    assert other.stat().st_size == record * 5000


def test_no_patch_for_daemon_argv_or_zero_cap(tmp_path: Path) -> None:
    log_file = tmp_path / "job.log"
    assert logcap.install(["/usr/local/bin/scrapyd"]) is False
    assert not logcap.is_installed()
    assert logcap.install(_crawler_argv(log_file, 0)) is False
    assert not logcap.is_installed()
    handler = _make_handler(log_file)
    _emit(handler, 1024, 100)
    handler.close()
    assert log_file.stat().st_size == 1024 * 100
    assert not hasattr(handler, "_dopilot_cap")


# --- TC-01g: activation is decided by argv only --------------------------------


def test_activation_requires_full_crawler_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "job.log"
    full = _crawler_argv(log_file, 4096)
    assert logcap.parse_crawler_argv(full) == (4096, str(log_file))

    no_job = [a for a in full if not a.startswith("_job=")]
    assert logcap.parse_crawler_argv(no_job) is None

    no_cap = [a for a in full if not a.startswith(logcap.SETTING_NAME)]
    no_cap = [a for i, a in enumerate(no_cap) if not (a == "-s" and i == len(no_cap) - 1)]
    assert logcap.parse_crawler_argv(no_cap) is None

    no_crawl = [a for a in full if a != "crawl"]
    assert logcap.parse_crawler_argv(no_crawl) is None

    # Environment variables are NOT an activation source.
    monkeypatch.setenv(logcap.SETTING_NAME, "4096")
    assert logcap.install(["/usr/local/bin/scrapyd"]) is False
    assert not logcap.is_installed()

    # Glued ``-sKEY=VAL`` form is also understood.
    glued = ["runner.py", "crawl", "x", "-a", "_job=1", f"-sLOG_FILE={log_file}",
             f"-s{logcap.SETTING_NAME}=77"]
    assert logcap.parse_crawler_argv(glued) == (77, str(log_file))


# --- TC-01e: black-box subprocess driven by a real command line ----------------


SCRIPT = textwrap.dedent(
    """
    import logging, sys
    import dopilot_agent.logcap  # the .pth does exactly this at startup
    path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("LOG_FILE="))
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("crawler"); log.addHandler(h); log.setLevel(logging.INFO)
    chunk = "y" * 1023
    for _ in range(50 * 1024):
        log.info(chunk)
    h.close()
    print("FINISHED")
    """
)


def test_subprocess_is_capped_and_terminated(tmp_path: Path) -> None:
    log_file = tmp_path / "job.log"
    script = tmp_path / "fake_crawler.py"
    script.write_text(SCRIPT, encoding="utf-8")
    cap = 65536
    argv = [sys.executable, str(script), "crawl", "x", "-a", "_job=abc",
            "-s", f"LOG_FILE={log_file}", "-s", f"{logcap.SETTING_NAME}={cap}"]
    t0 = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert time.monotonic() - t0 < 10
    assert proc.returncode == -signal.SIGTERM, proc.stdout + proc.stderr
    assert "FINISHED" not in proc.stdout
    size = log_file.stat().st_size
    assert size <= cap + 1024 + len(logcap.truncation_marker(cap))
    assert size >= cap

    # Control: daemon-shaped argv (no crawl/_job/cap) is never capped.
    free_file = tmp_path / "free.log"
    proc = subprocess.run(
        [sys.executable, str(script), f"LOG_FILE={free_file}"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0
    assert "FINISHED" in proc.stdout
    assert free_file.stat().st_size == 50 * 1024 * 1024
