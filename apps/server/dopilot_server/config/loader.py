"""Config loading.

Reads a TOML file (path argument or ``DOPILOT_CONFIG`` env), applies the
``DOPILOT_*`` env overrides (env wins over TOML; TOML remains the default
source), enforces fail-closed web auth, and returns a :class:`Settings`.

dopilot uses its own TOML loader under ``configs/`` — it does NOT inherit the
scrapydweb ``scrapydweb_settings_v11.py`` / ``os.getcwd()`` form.

Fail-closed auth (phase 2.2) lives HERE, at the production startup boundary,
NOT in :class:`Settings` construction — tests and dependency overrides build
``Settings`` directly via ``Settings.model_validate(...)`` and must stay able to
do so. Tests that need anonymous admin mode set ``auth.disabled=true``.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings import Settings

# Role-specific baked default config path. The CLI entrypoint passes this as
# ``default_path`` so the unified image runs server mode without an explicit
# ``DOPILOT_CONFIG`` (precedence: explicit path > DOPILOT_CONFIG > this default).
DEFAULT_CONFIG_PATH = "/app/configs/server.toml"


class ConfigError(Exception):
    """Raised when no config can be located, the file is unreadable, an env
    override is malformed, or fail-closed auth has no credentials."""


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


# Env override surface (phase 2.2). Each entry maps a ``DOPILOT_*`` env var to a
# ``(section, attribute)`` on :class:`Settings`. Env wins over TOML. List/nested
# fields (e.g. ``[nodes].agents``) are intentionally NOT env-overridable.
_STR_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    ("DOPILOT_SERVER_HOST", "server", "host"),
    ("DOPILOT_SERVER_PUBLIC_URL", "server", "public_url"),
    ("DOPILOT_DATABASE_URL", "database", "url"),
    ("DOPILOT_ADMIN_USERNAME", "auth", "admin_username"),
    ("DOPILOT_ADMIN_PASSWORD", "auth", "admin_password"),
    # Phase 2.2.2: the static admin API token. ``token_secret`` has NO env
    # override (TOML-only signing key); the removed ``DOPILOT_ADMIN_API_SECRET``
    # has no effect and no compatibility alias.
    ("DOPILOT_ADMIN_API_TOKEN", "auth", "admin_api_token"),
    ("DOPILOT_AGENT_SHARED_TOKEN", "agent_auth", "shared_token"),
    ("DOPILOT_REDIS_URL", "redis", "url"),
    ("DOPILOT_REDIS_CONSUMER_NAME", "redis", "consumer_name"),
    ("DOPILOT_SERVER_SHARED_TOKEN", "agents", "server_shared_token"),
    ("DOPILOT_LOGS_ROOT_DIR", "logs", "root_dir"),
    ("DOPILOT_ARTIFACTS_ROOT_DIR", "artifacts", "root_dir"),
    ("DOPILOT_I18N_LOCALE", "i18n", "locale"),
    ("DOPILOT_I18N_TIMEZONE", "i18n", "timezone"),
    ("DOPILOT_SCHEDULER_TIMEZONE", "scheduler", "timezone"),
)

_INT_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    ("DOPILOT_SERVER_PORT", "server", "port"),
    ("DOPILOT_ACCESS_TOKEN_TTL_MINUTES", "auth", "access_token_ttl_minutes"),
    ("DOPILOT_STREAM_TOKEN_TTL_SECONDS", "auth", "stream_token_ttl_seconds"),
    ("DOPILOT_REDIS_STREAM_MAXLEN_COMMANDS", "redis", "stream_maxlen_commands"),
    ("DOPILOT_REDIS_STREAM_MAXLEN_EVENTS", "redis", "stream_maxlen_events"),
    ("DOPILOT_REDIS_STREAM_MAXLEN_LOGS", "redis", "stream_maxlen_logs"),
    ("DOPILOT_REDIS_LOG_RETENTION_SECONDS", "redis", "log_retention_seconds"),
    ("DOPILOT_HEARTBEAT_TIMEOUT_SECONDS", "agents", "heartbeat_timeout_seconds"),
    ("DOPILOT_STALLED_ATTEMPT_SECONDS", "agents", "stalled_attempt_seconds"),
    (
        "DOPILOT_LOST_AFTER_STALLED_SECONDS",
        "agents",
        "lost_after_stalled_seconds",
    ),
    (
        "DOPILOT_LOG_BACKGROUND_DRAIN_INTERVAL_SECONDS",
        "logs",
        "background_drain_interval_seconds",
    ),
    (
        "DOPILOT_LOG_REALTIME_DRAIN_INTERVAL_SECONDS",
        "logs",
        "realtime_drain_interval_seconds",
    ),
    (
        "DOPILOT_LOG_STATUS_POLL_INTERVAL_SECONDS",
        "logs",
        "status_poll_interval_seconds",
    ),
    ("DOPILOT_LOG_MAX_TAIL_BYTES_PER_PULL", "logs", "max_tail_bytes_per_pull"),
    ("DOPILOT_LOG_EOF_STABLE_SECONDS", "logs", "eof_stable_seconds"),
    (
        "DOPILOT_LOG_FINAL_DRAIN_HARD_TIMEOUT_SECONDS",
        "logs",
        "final_drain_hard_timeout_seconds",
    ),
    ("DOPILOT_LOG_DRAIN_TIMEOUT_SECONDS", "logs", "log_drain_timeout_seconds"),
    (
        "DOPILOT_LOG_UNREACHABLE_LOST_SECONDS",
        "logs",
        "unreachable_lost_seconds",
    ),
    ("DOPILOT_LOG_RETENTION_DAYS", "logs", "retention_days"),
    ("DOPILOT_LOG_FIRST_SCREEN_MAX_LINES", "logs", "first_screen_max_lines"),
    ("DOPILOT_LOG_FIRST_SCREEN_MAX_BYTES", "logs", "first_screen_max_bytes"),
)

_BOOL_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    ("DOPILOT_AUTH_DISABLED", "auth", "disabled"),
    ("DOPILOT_REDIS_REQUIRE_AOF", "redis", "require_aof"),
    ("DOPILOT_SCHEDULER_ENABLED", "scheduler", "enabled"),
)

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _parse_int(env_var: str, raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        raise ConfigError(
            f"Invalid integer for {env_var}: {raw!r}"
        ) from None


def _parse_bool(env_var: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(
        f"Invalid boolean for {env_var}: {raw!r} "
        f"(expected one of true/false/1/0/yes/no/on/off)"
    )


def _apply_env_overrides(settings: Settings) -> None:
    """Apply ``DOPILOT_*`` scalar overrides in place (env wins over TOML)."""
    for env_var, section, attr in _STR_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is not None:
            setattr(getattr(settings, section), attr, raw)
    for env_var, section, attr in _INT_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is not None:
            setattr(getattr(settings, section), attr, _parse_int(env_var, raw))
    for env_var, section, attr in _BOOL_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is not None:
            setattr(getattr(settings, section), attr, _parse_bool(env_var, raw))


def _apply_machine_token_fallback(settings: Settings) -> None:
    """Default empty machine tokens to the static ``admin_api_token``.

    Single-secret posture: when ``[agent_auth].shared_token`` and/or
    ``[agents].server_shared_token`` are empty, derive them from
    ``auth.admin_api_token`` (set via TOML or ``DOPILOT_ADMIN_API_TOKEN``). This
    runs AFTER env overrides, so an explicit ``DOPILOT_AGENT_SHARED_TOKEN`` /
    ``DOPILOT_SERVER_SHARED_TOKEN`` (or a non-empty TOML value) wins.

    Phase 2.2.2 changed the fallback source from ``token_secret`` (a required
    fail-closed credential, so machine auth was always ON in production) to the
    OPTIONAL ``admin_api_token``: with no ``admin_api_token`` and no explicit
    split tokens, machine auth falls back to OFF (config-present-or-off). Set
    ``admin_api_token`` (or both split tokens) to keep machine auth ON.
    """
    secret = (settings.auth.admin_api_token or "").strip()
    if not secret:
        return
    if not (settings.agent_auth.shared_token or "").strip():
        settings.agent_auth.shared_token = secret
    if not (settings.agents.server_shared_token or "").strip():
        settings.agents.server_shared_token = secret


# Minimum length for a non-empty static ``admin_api_token`` (phase 2.2.2).
_ADMIN_API_TOKEN_MIN_LEN = 16


def _validate_admin_api_token(settings: Settings) -> None:
    """Reject a non-empty ``admin_api_token`` shorter than the minimum length.

    Empty / unset is allowed (machine auth simply falls back to OFF). A
    non-empty but too-short token is almost certainly a misconfiguration, so we
    hard-fail at the loader boundary rather than in :class:`Settings`
    construction (so tests / dependency overrides can still build short-token
    Settings directly).
    """
    token = (settings.auth.admin_api_token or "").strip()
    if token and len(token) < _ADMIN_API_TOKEN_MIN_LEN:
        raise ConfigError(
            "auth.admin_api_token is too short: a non-empty admin API token "
            f"must be at least {_ADMIN_API_TOKEN_MIN_LEN} characters "
            "(set DOPILOT_ADMIN_API_TOKEN or auth.admin_api_token, or leave it "
            "empty)."
        )


def _enforce_fail_closed_auth(settings: Settings) -> None:
    """Refuse to boot with anonymous admin unless it was explicitly requested.

    Web admin auth is fail-closed: if it is not disabled but any credential is
    missing/empty, raise :class:`ConfigError`. The documented dev escape hatch
    is ``DOPILOT_AUTH_DISABLED=true`` (``auth.disabled``).
    """
    auth = settings.auth
    if auth.disabled:
        return
    missing = [
        name
        for name, value in (
            ("admin_username", auth.admin_username),
            ("admin_password", auth.admin_password),
            ("token_secret", auth.token_secret),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise ConfigError(
            "Web admin auth is fail-closed: missing/empty "
            f"{', '.join(missing)}. Provide admin_username and admin_password "
            "(TOML or DOPILOT_ADMIN_USERNAME / DOPILOT_ADMIN_PASSWORD) and "
            "token_secret (TOML-only signing key, no env override), or set "
            "DOPILOT_AUTH_DISABLED=true to run anonymously in development."
        )


def load_settings(
    path: str | None = None, *, default_path: str | None = None
) -> Settings:
    """Load :class:`Settings` from a TOML file.

    Resolution order for the file path: explicit ``path`` argument, else the
    ``DOPILOT_CONFIG`` environment variable, else ``default_path`` (the CLI
    entrypoint passes the role default so the image runs without an explicit
    ``DOPILOT_CONFIG``). If none is set, or the file is missing, a
    :class:`ConfigError` is raised.

    ``DOPILOT_*`` env vars (see ``_STR_OVERRIDES`` / ``_INT_OVERRIDES`` /
    ``_BOOL_OVERRIDES``) override the matching TOML scalar — env wins over TOML.
    A malformed integer/boolean env value raises :class:`ConfigError` naming the
    env var. After overrides, empty machine tokens fall back to the static
    ``admin_api_token``, a non-empty-but-too-short ``admin_api_token`` is
    rejected, then web admin auth is enforced fail-closed.
    """
    resolved = path or os.environ.get("DOPILOT_CONFIG") or default_path
    if not resolved:
        raise ConfigError(
            "No config provided: pass a path or set the DOPILOT_CONFIG "
            "environment variable."
        )

    config_path = Path(resolved)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        raw = _read_toml(config_path)
    except (OSError, tomllib.TOMLDecodeError) as exc:  # pragma: no cover
        raise ConfigError(f"Failed to read config {config_path}: {exc}") from exc

    settings = Settings.model_validate(raw)
    _apply_env_overrides(settings)
    _validate_admin_api_token(settings)
    _apply_machine_token_fallback(settings)
    _enforce_fail_closed_auth(settings)
    return settings


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return load_settings()


def get_settings() -> Settings:
    """FastAPI dependency returning a cached singleton :class:`Settings`.

    Tests override this via ``app.dependency_overrides[get_settings]`` so the
    lru_cache is never exercised in the test client path.
    """
    return _cached_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (useful in tests / config reloads)."""
    _cached_settings.cache_clear()
