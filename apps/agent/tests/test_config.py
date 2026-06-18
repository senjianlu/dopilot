"""Tests for the TOML loader and env overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
from dopilot_agent.config.loader import ConfigError, load_settings

TOML = """\
[agent]
agent_id = "from-toml"
host = "0.0.0.0"
port = 6810
workdir = "/agent-data"

[auth]
shared_token = "tok"

[capabilities]
scrapy = true
script = false
docker = false
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "agent.toml"
    cfg.write_text(TOML, encoding="utf-8")
    return cfg


def test_loads_from_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    cfg = _write_config(tmp_path)

    settings = load_settings(cfg)

    assert settings.agent.agent_id == "from-toml"
    assert settings.agent.workdir == "/agent-data"
    assert settings.auth.shared_token == "tok"
    assert settings.auth.enabled is True
    assert settings.capabilities.scrapy is True
    assert settings.capabilities.docker is False


def test_agent_id_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path)
    monkeypatch.setenv("AGENT_ID", "from-env")
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)

    settings = load_settings(cfg)

    assert settings.agent.agent_id == "from-env"


def test_workdir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.setenv("AGENT_WORKDIR", "/custom/workdir")

    settings = load_settings(cfg)

    assert settings.agent.workdir == "/custom/workdir"


def test_missing_config_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOPILOT_CONFIG", raising=False)
    with pytest.raises(ConfigError):
        load_settings()


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "does-not-exist.toml")
