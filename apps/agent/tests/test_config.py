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
agent_token = "agent-machine-token"

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
    monkeypatch.delenv("DOPILOT_AGENT_TOKEN", raising=False)
    cfg = _write_config(tmp_path)

    settings = load_settings(cfg)

    assert settings.agent.agent_id == "from-toml"
    assert settings.agent.workdir == "/agent-data"
    # phase 2.2.3: the single server<->agent token lives on [agent].agent_token.
    assert settings.agent.agent_token == "agent-machine-token"
    assert settings.agent.machine_auth_enabled is True
    assert settings.capabilities.scrapy is True
    assert settings.capabilities.docker is False
    assert settings.scrapyd.start is False
    assert settings.scrapyd.host == "127.0.0.1"
    assert settings.scrapyd.port == 6802
    # phase 1.5 agent->server contact + redis transport
    assert settings.agent.server_url == "http://server:5000"
    assert settings.agent.heartbeat_interval_seconds == 7
    assert settings.redis.url == "redis://:pw@redis:6379/3"
    assert settings.redis.command_block_ms == 2000
    assert settings.redis.event_outbox_dir == "/agent-data/ob"


def test_redis_defaults_when_section_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    monkeypatch.delenv("DOPILOT_REDIS_URL", raising=False)
    monkeypatch.delenv("DOPILOT_AGENT_TOKEN", raising=False)
    cfg = tmp_path / "agent.toml"
    cfg.write_text(
        '[agent]\nagent_id = "x"\n[capabilities]\nscrapy = true\n',
        encoding="utf-8",
    )
    settings = load_settings(cfg)
    assert settings.redis.url == "redis://redis:6379/0"
    assert settings.redis.event_outbox_dir == "/agent-data/outbox"
    assert settings.agent.heartbeat_interval_seconds == 10
    # No token configured => machine auth OFF.
    assert settings.agent.agent_token == ""
    assert settings.agent.machine_auth_enabled is False


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


# --- phase 2.2.3: single server<->agent machine token -----------------------


def _clear_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AGENT_ID",
        "AGENT_WORKDIR",
        "DOPILOT_ADMIN_API_SECRET",
        "DOPILOT_ADMIN_API_TOKEN",
        "DOPILOT_AGENT_TOKEN",
        "DOPILOT_AGENT_SHARED_TOKEN",
        "DOPILOT_SERVER_SHARED_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)


def _write_empty_token_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "agent.toml"
    cfg.write_text(
        '[agent]\nagent_id = "x"\nagent_token = ""\n',
        encoding="utf-8",
    )
    return cfg


def test_agent_token_env_populates_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_token_env(monkeypatch)
    cfg = _write_empty_token_config(tmp_path)
    monkeypatch.setenv("DOPILOT_AGENT_TOKEN", "env-agent-machine-token")
    settings = load_settings(cfg)
    assert settings.agent.agent_token == "env-agent-machine-token"
    assert settings.agent.machine_auth_enabled is True


def test_admin_api_token_ignored_for_machine_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 2.2.3: the agent never derives its machine token from the admin API
    # token; with no agent_token set, machine auth stays OFF.
    _clear_token_env(monkeypatch)
    cfg = _write_empty_token_config(tmp_path)
    monkeypatch.setenv("DOPILOT_ADMIN_API_TOKEN", "static-admin-api-token")
    settings = load_settings(cfg)
    assert settings.agent.agent_token == ""
    assert settings.agent.machine_auth_enabled is False


def test_old_split_machine_token_envs_have_no_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 2.2.3: the removed split envs no longer fill any machine token.
    _clear_token_env(monkeypatch)
    cfg = _write_empty_token_config(tmp_path)
    monkeypatch.setenv("DOPILOT_AGENT_SHARED_TOKEN", "s2a-tok")
    monkeypatch.setenv("DOPILOT_SERVER_SHARED_TOKEN", "a2s-tok")
    settings = load_settings(cfg)
    assert settings.agent.agent_token == ""
    assert settings.agent.machine_auth_enabled is False


def test_old_admin_api_secret_env_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_token_env(monkeypatch)
    cfg = _write_empty_token_config(tmp_path)
    monkeypatch.setenv("DOPILOT_ADMIN_API_SECRET", "should-be-ignored")
    settings = load_settings(cfg)
    assert settings.agent.agent_token == ""
    assert settings.agent.machine_auth_enabled is False


def test_agent_token_env_wins_over_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_token_env(monkeypatch)
    cfg = _write_config(tmp_path)  # TOML: agent_token = "agent-machine-token"
    monkeypatch.setenv("DOPILOT_AGENT_TOKEN", "env-agent-machine-token")
    settings = load_settings(cfg)
    assert settings.agent.agent_token == "env-agent-machine-token"


def test_no_machine_auth_without_agent_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_token_env(monkeypatch)
    cfg = _write_empty_token_config(tmp_path)
    settings = load_settings(cfg)
    assert settings.agent.agent_token == ""
    assert settings.agent.machine_auth_enabled is False


def test_short_agent_token_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_token_env(monkeypatch)
    cfg = tmp_path / "agent.toml"
    cfg.write_text(
        '[agent]\nagent_id = "x"\nagent_token = "short"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(cfg)
    assert "agent_token" in str(exc.value)


def test_short_agent_token_env_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_token_env(monkeypatch)
    cfg = _write_empty_token_config(tmp_path)
    monkeypatch.setenv("DOPILOT_AGENT_TOKEN", "tiny")
    with pytest.raises(ConfigError) as exc:
        load_settings(cfg)
    assert "agent_token" in str(exc.value)


def test_default_path_used_when_no_explicit_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOPILOT_CONFIG", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    cfg = _write_config(tmp_path)
    settings = load_settings(default_path=str(cfg))
    assert settings.agent.agent_id == "from-toml"


def test_env_config_wins_over_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_WORKDIR", raising=False)
    env_cfg = _write_config(tmp_path)  # agent_id = from-toml
    default_cfg = tmp_path / "default.toml"
    default_cfg.write_text('[agent]\nagent_id = "from-default"\n', encoding="utf-8")
    monkeypatch.setenv("DOPILOT_CONFIG", str(env_cfg))
    settings = load_settings(default_path=str(default_cfg))
    assert settings.agent.agent_id == "from-toml"
