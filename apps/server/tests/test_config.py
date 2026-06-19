"""Config loader tests: TOML parse, env override, missing-config error."""

from __future__ import annotations

import textwrap

import pytest
from dopilot_server.config.loader import ConfigError, load_settings


def _write_toml(tmp_path) -> str:
    path = tmp_path / "dopilot.toml"
    path.write_text(
        textwrap.dedent(
            """
            [server]
            host = "1.2.3.4"
            port = 9001

            [database]
            url = "postgresql+psycopg://dopilot:dopilot@db:5432/dopilot"

            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "secret"

            [nodes]
            agents = ["agent-a:9100", "agent-b:9100"]

            [redis]
            url = "redis://:pw@redis:6379/2"
            stream_maxlen_logs = 500000
            consumer_name = "server-x"

            [agents]
            heartbeat_timeout_seconds = 15
            server_shared_token = "agent-server-tok"
            """
        ),
        encoding="utf-8",
    )
    return str(path)


def test_load_from_toml(tmp_path):
    settings = load_settings(_write_toml(tmp_path))
    assert settings.server.host == "1.2.3.4"
    assert settings.server.port == 9001
    assert settings.nodes.agents == ["agent-a:9100", "agent-b:9100"]
    assert settings.auth.enabled is True


def test_redis_and_agents_sections_parse(tmp_path):
    settings = load_settings(_write_toml(tmp_path))
    assert settings.redis.url == "redis://:pw@redis:6379/2"
    assert settings.redis.stream_maxlen_logs == 500000
    assert settings.redis.consumer_name == "server-x"
    # defaults for unspecified fields
    assert settings.redis.require_aof is True
    assert settings.redis.enabled is True
    assert settings.agents.heartbeat_timeout_seconds == 15
    assert settings.agents.stalled_attempt_seconds == 300  # default
    assert settings.agents.server_shared_token == "agent-server-tok"
    assert settings.agents.inbound_auth_enabled is True


def test_redis_agents_defaults_when_absent(tmp_path):
    path = tmp_path / "minimal.toml"
    path.write_text('[server]\nhost = "x"\n', encoding="utf-8")
    settings = load_settings(str(path))
    assert settings.redis.url == "redis://localhost:6379/0"
    assert settings.agents.heartbeat_timeout_seconds == 30
    assert settings.agents.inbound_auth_enabled is False  # no inbound token => off
    assert settings.logs.log_drain_timeout_seconds == 30


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "DOPILOT_DATABASE_URL",
        "postgresql+psycopg://dopilot:dopilot@override:5432/dopilot",
    )
    monkeypatch.setenv("DOPILOT_REDIS_URL", "redis://envhost:6390/9")
    settings = load_settings(_write_toml(tmp_path))
    assert "override:5432" in settings.database.url
    assert settings.redis.url == "redis://envhost:6390/9"


def test_missing_config_raises(monkeypatch):
    monkeypatch.delenv("DOPILOT_CONFIG", raising=False)
    with pytest.raises(ConfigError):
        load_settings()


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(str(tmp_path / "nope.toml"))


def test_auth_off_when_partial(tmp_path):
    path = tmp_path / "partial.toml"
    path.write_text(
        '[auth]\nadmin_username = "admin"\n', encoding="utf-8"
    )
    settings = load_settings(str(path))
    assert settings.auth.enabled is False
