"""Tests for the local container healthcheck CLI (phase 2.2.7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from dopilot_agent import healthcheck as hc
from dopilot_agent.scrapyd import client as scrapyd_client


def _write_config(tmp_path: Path, *, start: bool) -> Path:
    cfg = tmp_path / "agent.toml"
    cfg.write_text(
        "[agent]\n"
        'agent_id = "agent-test-1"\n'
        "[capabilities]\n"
        "scrapy = true\n"
        "[scrapyd]\n"
        f"start = {'true' if start else 'false'}\n"
        'host = "127.0.0.1"\n'
        "port = 6801\n",
        encoding="utf-8",
    )
    return cfg


def _use_config(monkeypatch: pytest.MonkeyPatch, cfg: Path) -> None:
    monkeypatch.setenv("DOPILOT_CONFIG", str(cfg))
    for var in ("AGENT_ID", "AGENT_WORKDIR", "DOPILOT_AGENT_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def _patch_scrapyd(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    # Force every ScrapydClient built by the healthcheck to use our mock
    # transport instead of opening a real socket.
    real_init = scrapyd_client.ScrapydClient.__init__

    def _init(self: Any, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(scrapyd_client.ScrapydClient, "__init__", _init)


def test_healthcheck_ok_when_scrapyd_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_config(monkeypatch, _write_config(tmp_path, start=True))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/daemonstatus.json"
        return httpx.Response(200, json={"status": "ok", "running": 0})

    _patch_scrapyd(monkeypatch, handler)
    assert hc.main() == 0


def test_healthcheck_fails_when_scrapyd_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_config(monkeypatch, _write_config(tmp_path, start=True))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("scrapyd unreachable", request=request)

    _patch_scrapyd(monkeypatch, handler)
    assert hc.main() == 1


def test_healthcheck_skips_scrapyd_when_unmanaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # start=false => external scrapyd; loading config is the only assertion and
    # no scrapyd probe is attempted (so a down scrapyd does not fail the check).
    _use_config(monkeypatch, _write_config(tmp_path, start=False))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("scrapyd must not be probed when start=false")

    _patch_scrapyd(monkeypatch, handler)
    assert hc.main() == 0


def test_healthcheck_fails_on_bad_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "agent.toml"
    cfg.write_text('[agent]\n# missing agent_id\n', encoding="utf-8")
    _use_config(monkeypatch, cfg)
    assert hc.main() == 1
