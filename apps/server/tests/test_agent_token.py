"""Agent-token helper, runtime injection, and CLI tests (phase 2.2.4).

Covers the server-side generation/persistence of the single server<->agent
token, its application to ``settings.agents.agent_token`` at the runtime
boundary, the ``create_app(settings)`` ``get_settings`` injection (so heartbeat
auth enforces the generated token), and the ``agent-token print`` CLI.
"""

from __future__ import annotations

import os
import stat
import textwrap

import pytest
from dopilot_server.agent_token import (
    ensure_runtime_agent_token,
    resolve_agent_token,
    token_file_path,
)
from dopilot_server.app import _agent_token_cli, create_app
from dopilot_server.config.loader import get_settings
from dopilot_server.config.settings import Settings
from dopilot_server.db.engine import get_session
from httpx import ASGITransport, AsyncClient


def _settings(data_dir: str, agent_token: str | None = None) -> Settings:
    data: dict = {
        "database": {"url": "sqlite+aiosqlite:///:memory:"},
        "auth": {"disabled": True},
        "server": {"data_dir": data_dir},
    }
    if agent_token is not None:
        data["agents"] = {"agent_token": agent_token}
    return Settings.model_validate(data)


# --- resolve / persist -------------------------------------------------------


def test_missing_token_generates_at_expected_path(tmp_path):
    settings = _settings(str(tmp_path))
    expected = tmp_path / "secrets" / "agent-token"
    assert token_file_path(settings) == expected
    assert not expected.exists()

    result = resolve_agent_token(settings)
    assert result.source == "generated"
    assert result.path == expected
    assert expected.is_file()
    assert expected.read_text(encoding="utf-8").strip() == result.token


def test_generated_token_is_long_enough(tmp_path):
    result = resolve_agent_token(_settings(str(tmp_path)))
    assert len(result.token) >= 16


def test_generated_token_file_mode_is_owner_only(tmp_path):
    result = resolve_agent_token(_settings(str(tmp_path)))
    mode = stat.S_IMODE(os.stat(result.path).st_mode)
    # Owner-only where supported (POSIX). Skip the assert on platforms that do
    # not honor chmod bits.
    if os.name == "posix":
        assert mode == 0o600


def test_second_call_reuses_persisted_token(tmp_path):
    settings = _settings(str(tmp_path))
    first = resolve_agent_token(settings)
    assert first.source == "generated"
    # A fresh settings object pointing at the same data dir must read the file.
    second = resolve_agent_token(_settings(str(tmp_path)))
    assert second.source == "disk"
    assert second.token == first.token


def test_configured_token_wins_and_does_not_touch_file(tmp_path):
    settings = _settings(str(tmp_path), agent_token="configured-token-1234567")
    result = resolve_agent_token(settings)
    assert result.source == "configured"
    assert result.token == "configured-token-1234567"
    assert result.path is None
    # No generated-token file is created when a token is configured.
    assert not (tmp_path / "secrets" / "agent-token").exists()


def test_ensure_runtime_applies_generated_token(tmp_path):
    settings = _settings(str(tmp_path))
    assert settings.agents.machine_auth_enabled is False
    result = ensure_runtime_agent_token(settings)
    assert settings.agents.agent_token == result.token
    assert settings.agents.machine_auth_enabled is True
    assert result.is_generated_path is True


def test_ensure_runtime_keeps_configured_token(tmp_path):
    settings = _settings(str(tmp_path), agent_token="configured-token-1234567")
    result = ensure_runtime_agent_token(settings)
    assert settings.agents.agent_token == "configured-token-1234567"
    assert result.source == "configured"
    assert result.is_generated_path is False


# --- create_app get_settings injection -> heartbeat auth ---------------------


def _heartbeat_body(agent_id: str = "agent-1") -> dict:
    return {
        "agent_id": agent_id,
        "version": "0.1.0",
        "capabilities": {"scrapy": True, "script": False, "docker": False},
        "load": {"running_attempts": 0},
        "detail": {
            "scrapyd": {"port": 6801, "managed": True},
            "redis": {"connected": True, "command_consumer": {"running": True}},
        },
        "endpoint": "agent:6800",
        "reported_at": "2026-06-22T00:00:00Z",
    }


async def test_create_app_injects_generated_settings_into_heartbeat_auth(
    tmp_path, db_session
):
    # Generated token applied at the runtime boundary, then create_app(settings)
    # must expose THAT settings object via Depends(get_settings) so heartbeat
    # auth enforces the generated token (the feasibility blocker).
    settings = _settings(str(tmp_path))
    result = ensure_runtime_agent_token(settings)
    assert settings.agents.machine_auth_enabled is True

    app = create_app(settings)
    # Deliberately do NOT override get_settings — create_app must have wired it.
    assert app.dependency_overrides[get_settings]() is settings

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No token -> 401 (machine auth is ON via the generated token).
        resp = await client.post(
            "/api/v1/agents/agent-1/heartbeat", json=_heartbeat_body()
        )
        assert resp.status_code == 401
        # Correct generated token -> 200.
        resp = await client.post(
            "/api/v1/agents/agent-1/heartbeat",
            json=_heartbeat_body(),
            headers={"Authorization": f"Bearer {result.token}"},
        )
        assert resp.status_code == 200


# --- CLI ---------------------------------------------------------------------


def _write_cli_config(tmp_path) -> str:
    cfg = tmp_path / "server.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            [server]
            data_dir = "{tmp_path / 'data'}"

            [auth]
            disabled = true
            """
        ),
        encoding="utf-8",
    )
    return str(cfg)


def test_cli_print_quiet_outputs_only_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DOPILOT_CONFIG", _write_cli_config(tmp_path))
    rc = _agent_token_cli(["print", "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    token = out[0]
    assert len(token) >= 16
    # The same token was persisted under the configured data dir.
    persisted = (tmp_path / "data" / "secrets" / "agent-token").read_text(
        encoding="utf-8"
    ).strip()
    assert persisted == token


def test_cli_print_includes_env_var_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DOPILOT_CONFIG", _write_cli_config(tmp_path))
    rc = _agent_token_cli(["print"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DOPILOT_AGENT_TOKEN=" in out


def test_cli_works_without_db_or_redis(tmp_path, monkeypatch, capsys):
    # The CLI must not need DB/Redis/ASGI: a config with an unreachable DB/Redis
    # URL still prints a token (no connection is attempted).
    cfg = tmp_path / "server.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            [server]
            data_dir = "{tmp_path / 'data'}"

            [database]
            url = "postgresql+psycopg://nope:nope@unreachable:5432/nope"

            [redis]
            url = "redis://unreachable:6379/0"

            [auth]
            disabled = true
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOPILOT_CONFIG", str(cfg))
    rc = _agent_token_cli(["print", "--quiet"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_cli_print_reports_configured_source(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "server.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            [server]
            data_dir = "{tmp_path / 'data'}"

            [auth]
            disabled = true

            [agents]
            agent_token = "configured-token-1234567"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOPILOT_CONFIG", str(cfg))
    rc = _agent_token_cli(["print"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "configured-token-1234567" in out
    assert "configured" in out
    # No generated-token file written when configured.
    assert not (tmp_path / "data" / "secrets" / "agent-token").exists()


def test_cli_unknown_action_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPILOT_CONFIG", _write_cli_config(tmp_path))
    with pytest.raises(SystemExit):
        _agent_token_cli(["bogus"])
