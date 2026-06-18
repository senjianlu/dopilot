"""Unit tests for the scrapyd subprocess manager (no real scrapyd binary).

These cover the parts that do not require launching scrapyd: conf generation,
directory layout, and base_url/port/pid accessors. ``start()`` itself is only
exercised in the compose smoke test (a real scrapyd binary), not here.
"""

from __future__ import annotations

from pathlib import Path

from dopilot_agent.scrapyd.process import ScrapydProcess


def test_write_conf_creates_dirs_and_conf(tmp_path: Path) -> None:
    proc = ScrapydProcess(workdir=tmp_path, host="127.0.0.1", port=6801)
    conf_path = proc.write_conf()

    assert conf_path == tmp_path / "scrapyd" / "scrapyd.conf"
    text = conf_path.read_text(encoding="utf-8")
    assert "bind_address = 127.0.0.1" in text
    assert "http_port    = 6801" in text
    for sub in ("eggs", "logs", "dbs", "items"):
        assert (tmp_path / "scrapyd" / sub).is_dir()
        assert f"{sub}_dir" in text


def test_accessors_when_not_started(tmp_path: Path) -> None:
    proc = ScrapydProcess(workdir=tmp_path, host="127.0.0.1", port=6801)
    assert proc.is_running() is False
    assert proc.pid is None
    assert proc.base_url == "http://127.0.0.1:6801"
    assert proc.logs_dir() == tmp_path / "scrapyd" / "logs"


def test_stop_is_noop_when_never_started(tmp_path: Path) -> None:
    proc = ScrapydProcess(workdir=tmp_path)
    proc.stop()  # must not raise
    assert proc.is_running() is False
