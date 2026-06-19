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
server_url = "http://server:5000"
heartbeat_interval_seconds = 7
server_shared_token = "agent-server-tok"

[auth]
shared_token = "tok"

[capabilities]
scrapy = true
script = false
docker = false

[scrapyd]
start = false
host = "127.0.0.1"
port = 6802

[redis]
url = "redis://:pw@redis:6379/3"
command_block_ms = 2000
event_outbox_dir = "/agent-data/ob"
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
    assert settings.scrapyd.start is False
    assert settings.scrapyd.host == "127.0.0.1"
    assert settings.scrapyd.port == 6802
    # phase 1.5 agent->server contact + redis transport
    assert settings.agent.server_url == "http://server:5000"
    assert settings.agent.heartbeat_interval_seconds == 7
    assert settings.agent.server_shared_token == "agent-server-tok"
    assert settings.redis.url == "redis://:pw@redis:6379/3"
    assert settings.redis.command_block_ms == 2000
    assert settings.redis.event_outbox_dir == "/agent-data/ob"


def test_redis_defaults_when_section_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    monkeypatch.delenv("DOPILOT_REDIS_URL", raising=False)
    cfg = tmp_path / "agent.toml"
    cfg.write_text(
        '[agent]\nagent_id = "x"\n[capabilities]\nscrapy = true\n',
        encoding="utf-8",
    )
    settings = load_settings(cfg)
    assert settings.redis.url == "redis://redis:6379/0"
    assert settings.redis.event_outbox_dir == "/agent-data/outbox"
    assert settings.agent.heartbeat_interval_seconds == 10
    assert settings.agent.server_shared_token == ""


def test_redis_url_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    monkeypatch.setenv("DOPILOT_REDIS_URL", "redis://envhost:6399/8")
    settings = load_settings(cfg)
    assert settings.redis.url == "redis://envhost:6399/8"


def test_scrapyd_defaults_when_section_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    cfg = tmp_path / "agent.toml"
    cfg.write_text(
        '[agent]\nagent_id = "x"\n[capabilities]\nscrapy = true\n',
        encoding="utf-8",
    )

    settings = load_settings(cfg)

    # [scrapyd] omitted => defaults: start on, container-internal 127.0.0.1:6801.
    assert settings.scrapyd.start is True
    assert settings.scrapyd.host == "127.0.0.1"
    assert settings.scrapyd.port == 6801


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
