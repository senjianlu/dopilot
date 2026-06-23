"""TOML config loader for the agent.

Loads settings from the path given by ``DOPILOT_CONFIG`` (or an explicit path).
Supports a small set of environment overrides used by container deployments.
``get_settings()`` is a cached singleton helper retained for direct callers.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings import (
    AgentSettings,
    Capabilities,
    RedisSettings,
    ScrapydSettings,
    Settings,
)

# Minimum length for a non-empty server<->agent ``agent_token`` (phase 2.2.3),
# matching the server-side check.
_AGENT_TOKEN_MIN_LEN = 16

# Role-specific baked default config path. ``main()`` passes this as
# ``default_path`` so the unified image runs agent mode without an explicit
# ``DOPILOT_CONFIG`` (precedence: explicit path > DOPILOT_CONFIG > this default).
DEFAULT_CONFIG_PATH = "/app/configs/agent.toml"


class ConfigError(Exception):
    """Raised when the agent config is missing or unreadable."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in config file {path}: {exc}") from exc


def load_settings(
    path: str | os.PathLike[str] | None = None,
    *,
    default_path: str | None = None,
) -> Settings:
    """Load agent settings from TOML.

    Resolution order for the path: explicit ``path`` argument, then the
    ``DOPILOT_CONFIG`` environment variable, then ``default_path`` (``main()``
    passes the baked agent default so the image runs without an explicit
    ``DOPILOT_CONFIG``). Environment overrides applied after parsing:
    ``AGENT_ID`` -> ``[agent].agent_id``, ``AGENT_WORKDIR`` -> ``[agent].workdir``,
    ``DOPILOT_SERVER_URL`` -> ``[agent].server_url`` (the server HTTP base URL the
    agent uses for heartbeat and artifact/wheel fetch; needed by agent-only / K3s
    deployments where the baked ``http://server:5000`` does not resolve),
    ``DOPILOT_REDIS_URL`` -> ``[redis].url``, ``DOPILOT_AGENT_TOKEN`` ->
    ``[agent].agent_token`` (the single server<->agent machine token).

    Phase 2.2.3 collapsed the split machine tokens into one. The old envs
    ``DOPILOT_AGENT_SHARED_TOKEN`` / ``DOPILOT_SERVER_SHARED_TOKEN`` and the
    admin-token fallback (``DOPILOT_ADMIN_API_TOKEN``) no longer fill any agent
    machine token and have no effect: agents are never given or derive from the
    admin API token. A non-empty ``agent_token`` shorter than 16 characters
    raises :class:`ConfigError`; empty/missing keeps machine auth OFF.
    """
    raw_path = (
        path if path is not None else os.environ.get("DOPILOT_CONFIG")
    ) or default_path
    if not raw_path:
        raise ConfigError(
            "no config path provided; set DOPILOT_CONFIG or pass path explicitly"
        )

    data = _read_toml(Path(raw_path))

    agent_section: dict[str, Any] = dict(data.get("agent") or {})
    cap_section: dict[str, Any] = dict(data.get("capabilities") or {})
    scrapyd_section: dict[str, Any] = dict(data.get("scrapyd") or {})
    redis_section: dict[str, Any] = dict(data.get("redis") or {})

    env_agent_id = os.environ.get("AGENT_ID")
    if env_agent_id:
        agent_section["agent_id"] = env_agent_id
    env_workdir = os.environ.get("AGENT_WORKDIR")
    if env_workdir:
        agent_section["workdir"] = env_workdir
    # Server HTTP base URL (heartbeat + artifact/wheel fetch): env wins over TOML.
    # Agent-only / K3s deployments set this because the baked compose default
    # ``http://server:5000`` only resolves inside the all-in-one compose network.
    env_server_url = os.environ.get("DOPILOT_SERVER_URL")
    if env_server_url:
        agent_section["server_url"] = env_server_url
    env_redis_url = os.environ.get("DOPILOT_REDIS_URL")
    if env_redis_url:
        redis_section["url"] = env_redis_url

    # Single server<->agent machine token (phase 2.2.3): env wins over TOML.
    # The old split envs and the admin-token fallback were removed and have no
    # effect — agents never receive or derive from the admin API token.
    env_agent_token = os.environ.get("DOPILOT_AGENT_TOKEN")
    if env_agent_token is not None:
        agent_section["agent_token"] = env_agent_token

    if not agent_section.get("agent_id"):
        raise ConfigError("missing required setting: [agent].agent_id")

    token = str(agent_section.get("agent_token") or "").strip()
    if token and len(token) < _AGENT_TOKEN_MIN_LEN:
        raise ConfigError(
            "agent.agent_token is too short: a non-empty server<->agent token "
            f"must be at least {_AGENT_TOKEN_MIN_LEN} characters "
            "(set DOPILOT_AGENT_TOKEN or [agent].agent_token, or leave it empty)."
        )

    return Settings(
        agent=AgentSettings(**agent_section),
        capabilities=Capabilities(**cap_section),
        scrapyd=ScrapydSettings(**scrapyd_section),
        redis=RedisSettings(**redis_section),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings helper for direct library callers."""
    return load_settings()
