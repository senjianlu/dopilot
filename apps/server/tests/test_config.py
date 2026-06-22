"""Config loader tests: TOML parse, env override, missing-config error."""

from __future__ import annotations

import textwrap

import pytest
from dopilot_server.config.loader import ConfigError, load_settings
from dopilot_server.config.settings import AuthSettings


def test_auth_settings_enabled_variants():
    creds = {
        "admin_username": "admin",
        "admin_password": "pw",
        "token_secret": "secret",
    }
    # All three present, not disabled => ON.
    assert AuthSettings(**creds).enabled is True
    # Disabled flag wins even with full creds => OFF.
    assert AuthSettings(disabled=True, **creds).enabled is False
    # Missing a credential => OFF (regardless of disabled).
    assert AuthSettings(admin_username="admin").enabled is False
    # No creds at all => OFF.
    assert AuthSettings().enabled is False
    assert AuthSettings().disabled is False  # default
    # admin_api_token is an additional credential; it does NOT enable web auth.
    assert AuthSettings(admin_api_token="x" * 32).enabled is False
    assert AuthSettings(**creds, admin_api_token="x" * 32).enabled is True


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
    # auth.disabled keeps the minimal (credential-less) config loadable under
    # phase 2.2 fail-closed auth.
    path = tmp_path / "minimal.toml"
    path.write_text(
        '[server]\nhost = "x"\n\n[auth]\ndisabled = true\n', encoding="utf-8"
    )
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


def test_fail_closed_when_partial_auth(tmp_path):
    # phase 2.2: partial creds + not disabled => refuse to boot (fail-closed).
    path = tmp_path / "partial.toml"
    path.write_text('[auth]\nadmin_username = "admin"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_settings(str(path))
    assert "admin_password" in str(exc.value)
    assert "token_secret" in str(exc.value)


def test_fail_closed_when_no_auth_section(tmp_path):
    path = tmp_path / "noauth.toml"
    path.write_text('[server]\nhost = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(str(path))


def test_auth_disabled_allows_anonymous(tmp_path):
    # Explicit disabled mode boots without credentials; enabled stays False.
    path = tmp_path / "disabled.toml"
    path.write_text('[auth]\ndisabled = true\n', encoding="utf-8")
    settings = load_settings(str(path))
    assert settings.auth.disabled is True
    assert settings.auth.enabled is False


def test_auth_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPILOT_AUTH_DISABLED", "true")
    path = tmp_path / "noauth.toml"
    path.write_text('[server]\nhost = "x"\n', encoding="utf-8")
    settings = load_settings(str(path))
    assert settings.auth.disabled is True
    assert settings.auth.enabled is False


def test_env_overrides_scalars(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPILOT_SERVER_HOST", "9.9.9.9")
    monkeypatch.setenv("DOPILOT_SERVER_PORT", "7777")
    monkeypatch.setenv("DOPILOT_ADMIN_PASSWORD", "env-pw")
    monkeypatch.setenv("DOPILOT_ADMIN_API_TOKEN", "env-admin-api-token")
    monkeypatch.setenv("DOPILOT_SERVER_SHARED_TOKEN", "env-server-tok")
    monkeypatch.setenv("DOPILOT_REDIS_STREAM_MAXLEN_LOGS", "42")
    monkeypatch.setenv("DOPILOT_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("DOPILOT_SCHEDULER_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("DOPILOT_REDIS_REQUIRE_AOF", "false")
    settings = load_settings(_write_toml(tmp_path))
    assert settings.server.host == "9.9.9.9"  # env wins over TOML 1.2.3.4
    assert settings.server.port == 7777
    assert settings.auth.admin_password == "env-pw"
    # token_secret is TOML-only (no env override) => stays the TOML value.
    assert settings.auth.token_secret == "secret"
    assert settings.auth.admin_api_token == "env-admin-api-token"
    assert settings.agents.server_shared_token == "env-server-tok"
    assert settings.redis.stream_maxlen_logs == 42
    assert settings.scheduler.enabled is True
    assert settings.scheduler.timezone == "Asia/Shanghai"
    assert settings.redis.require_aof is False


def test_admin_api_secret_env_has_no_effect(tmp_path, monkeypatch):
    # Phase 2.2.2: the removed DOPILOT_ADMIN_API_SECRET must not populate
    # token_secret (or anything else). token_secret stays the TOML value.
    monkeypatch.setenv("DOPILOT_ADMIN_API_SECRET", "should-be-ignored")
    settings = load_settings(_write_toml(tmp_path))
    assert settings.auth.token_secret == "secret"  # from TOML, unchanged
    assert settings.auth.admin_api_token is None


def test_env_fills_missing_username_password_to_pass_fail_closed(tmp_path, monkeypatch):
    # token_secret is TOML-only; env supplies the username/password -> auth ON.
    path = tmp_path / "auth.toml"
    path.write_text('[auth]\ntoken_secret = "secret"\n', encoding="utf-8")
    monkeypatch.setenv("DOPILOT_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("DOPILOT_ADMIN_PASSWORD", "pw")
    settings = load_settings(str(path))
    assert settings.auth.enabled is True


def test_env_invalid_int_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPILOT_SERVER_PORT", "not-an-int")
    with pytest.raises(ConfigError) as exc:
        load_settings(_write_toml(tmp_path))
    assert "DOPILOT_SERVER_PORT" in str(exc.value)


def test_env_invalid_bool_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPILOT_SCHEDULER_ENABLED", "maybe")
    with pytest.raises(ConfigError) as exc:
        load_settings(_write_toml(tmp_path))
    assert "DOPILOT_SCHEDULER_ENABLED" in str(exc.value)


# --- phase 2.2.2: static admin API token + machine-token fallback -----------


def test_admin_api_token_env_populates_field(tmp_path, monkeypatch):
    # DOPILOT_ADMIN_API_TOKEN populates auth.admin_api_token (and, since the
    # machine tokens are unset in this TOML, both fall back to it).
    monkeypatch.setenv("DOPILOT_ADMIN_API_TOKEN", "static-admin-api-token")
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            """
        ),
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    assert settings.auth.admin_api_token == "static-admin-api-token"
    # token_secret stays its own TOML signing key, unaffected.
    assert settings.auth.token_secret == "the-signing-secret"


def test_old_admin_api_secret_env_does_not_set_token_secret(tmp_path, monkeypatch):
    # Phase 2.2.2: DOPILOT_ADMIN_API_SECRET no longer populates token_secret; with
    # no TOML token_secret, auth stays fail-closed and the message names neither
    # the removed env nor the also-removed DOPILOT_TOKEN_SECRET.
    path = tmp_path / "noauth.toml"
    path.write_text('[server]\nhost = "x"\n', encoding="utf-8")
    monkeypatch.setenv("DOPILOT_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("DOPILOT_ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("DOPILOT_ADMIN_API_SECRET", "should-be-ignored")
    with pytest.raises(ConfigError) as exc:
        load_settings(str(path))
    assert "token_secret" in str(exc.value)
    assert "DOPILOT_ADMIN_API_SECRET" not in str(exc.value)
    assert "DOPILOT_TOKEN_SECRET" not in str(exc.value)


def test_machine_tokens_fall_back_to_admin_api_token(tmp_path, monkeypatch):
    # token_secret is TOML-only; the static admin_api_token (env) is the machine
    # token fallback source -> both machine tokens resolve to it.
    monkeypatch.setenv("DOPILOT_ADMIN_API_TOKEN", "static-admin-api-token")
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            """
        ),
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    # token_secret is NOT the machine-token source anymore.
    assert settings.agent_auth.shared_token == "static-admin-api-token"
    assert settings.agents.server_shared_token == "static-admin-api-token"
    assert settings.agent_auth.enabled is True
    assert settings.agents.inbound_auth_enabled is True


def test_split_machine_token_envs_override_fallback(tmp_path, monkeypatch):
    # Explicit split tokens win over the admin_api_token fallback.
    monkeypatch.setenv("DOPILOT_ADMIN_API_TOKEN", "static-admin-api-token")
    monkeypatch.setenv("DOPILOT_AGENT_SHARED_TOKEN", "s2a-tok")
    monkeypatch.setenv("DOPILOT_SERVER_SHARED_TOKEN", "a2s-tok")
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            """
        ),
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    assert settings.auth.admin_api_token == "static-admin-api-token"
    assert settings.agent_auth.shared_token == "s2a-tok"
    assert settings.agents.server_shared_token == "a2s-tok"


def test_toml_machine_token_not_overwritten_by_fallback(tmp_path):
    # A non-empty TOML machine token is left intact; only the empty one falls
    # back to admin_api_token.
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            admin_api_token = "the-admin-api-token"

            [agent_auth]
            shared_token = "toml-s2a"
            """
        ),
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    # TOML value preserved; the absent agents token falls back to admin_api_token.
    assert settings.agent_auth.shared_token == "toml-s2a"
    assert settings.agents.server_shared_token == "the-admin-api-token"


def test_no_machine_fallback_without_admin_api_token(tmp_path):
    # token_secret present (auth ON) but no admin_api_token => machine tokens stay
    # empty (machine auth config-present-or-off). token_secret is NOT a fallback.
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            """
        ),
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    assert settings.auth.enabled is True
    assert settings.agent_auth.shared_token in (None, "")
    assert settings.agents.server_shared_token in (None, "")
    assert settings.agent_auth.enabled is False
    assert settings.agents.inbound_auth_enabled is False


def test_no_fallback_when_admin_api_token_empty(tmp_path):
    # Anonymous dev mode (no admin_api_token): nothing to derive => stays empty.
    path = tmp_path / "disabled.toml"
    path.write_text('[auth]\ndisabled = true\n', encoding="utf-8")
    settings = load_settings(str(path))
    assert settings.agent_auth.shared_token in (None, "")
    assert settings.agents.server_shared_token in (None, "")


def test_empty_admin_api_token_is_allowed(tmp_path):
    # An explicitly empty admin_api_token loads fine (no min-length check).
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            admin_api_token = ""
            """
        ),
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    assert settings.auth.admin_api_token == ""


def test_short_admin_api_token_raises(tmp_path):
    # A non-empty admin_api_token shorter than 16 chars is rejected.
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            admin_api_token = "short"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(str(path))
    assert "admin_api_token" in str(exc.value)


def test_short_admin_api_token_env_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPILOT_ADMIN_API_TOKEN", "tiny")
    path = tmp_path / "cfg.toml"
    path.write_text(
        textwrap.dedent(
            """
            [auth]
            admin_username = "admin"
            admin_password = "pw"
            token_secret = "the-signing-secret"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_settings(str(path))


def test_default_path_used_when_no_explicit_or_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DOPILOT_CONFIG", raising=False)
    cfg = tmp_path / "server.toml"
    cfg.write_text('[auth]\ndisabled = true\n', encoding="utf-8")
    settings = load_settings(default_path=str(cfg))
    assert settings.auth.disabled is True


def test_env_config_wins_over_default_path(tmp_path, monkeypatch):
    env_cfg = tmp_path / "env.toml"
    env_cfg.write_text(
        '[server]\nhost = "envhost"\n[auth]\ndisabled = true\n', encoding="utf-8"
    )
    default_cfg = tmp_path / "default.toml"
    default_cfg.write_text(
        '[server]\nhost = "defaulthost"\n[auth]\ndisabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DOPILOT_CONFIG", str(env_cfg))
    settings = load_settings(default_path=str(default_cfg))
    assert settings.server.host == "envhost"


def test_explicit_path_wins_over_default_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DOPILOT_CONFIG", raising=False)
    explicit = tmp_path / "explicit.toml"
    explicit.write_text(
        '[server]\nhost = "explicithost"\n[auth]\ndisabled = true\n',
        encoding="utf-8",
    )
    default_cfg = tmp_path / "default.toml"
    default_cfg.write_text('[auth]\ndisabled = true\n', encoding="utf-8")
    settings = load_settings(str(explicit), default_path=str(default_cfg))
    assert settings.server.host == "explicithost"
