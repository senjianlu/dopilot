"""TOML config loader for the agent.

Loads settings from the path given by ``DOPILOT_CONFIG`` (or an explicit path).
Supports a small set of environment overrides used by container deployments.
``get_settings()`` is a cached singleton dependency that tests can override.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings import (
    AgentSettings,
    AuthSettings,
    Capabilities,
    RedisSettings,
    ScrapydSettings,
    Settings,
)

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
    ``DOPILOT_REDIS_URL`` -> ``[redis].url``, ``DOPILOT_AGENT_SHARED_TOKEN`` ->
    ``[auth].shared_token`` (server->agent), ``DOPILOT_SERVER_SHARED_TOKEN`` ->
    ``[agent].server_shared_token`` (agent->server).

    Single-secret fallback (phase 2.2.1): when a machine token is still empty
    after overrides, it defaults to ``DOPILOT_ADMIN_API_SECRET`` (loader-only on
    the agent — there is no agent settings field for the admin secret). An
    explicit split-token value (TOML or env) always wins over the fallback.
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
    auth_section: dict[str, Any] = dict(data.get("auth") or {})
    cap_section: dict[str, Any] = dict(data.get("capabilities") or {})
    scrapyd_section: dict[str, Any] = dict(data.get("scrapyd") or {})
    redis_section: dict[str, Any] = dict(data.get("redis") or {})

    env_agent_id = os.environ.get("AGENT_ID")
    if env_agent_id:
        agent_section["agent_id"] = env_agent_id
    env_workdir = os.environ.get("AGENT_WORKDIR")
    if env_workdir:
        agent_section["workdir"] = env_workdir
    env_redis_url = os.environ.get("DOPILOT_REDIS_URL")
    if env_redis_url:
        redis_section["url"] = env_redis_url

    # Machine-token env overrides (env wins over TOML), then single-secret
    # fallback to DOPILOT_ADMIN_API_SECRET for whichever stays empty.
    env_agent_shared = os.environ.get("DOPILOT_AGENT_SHARED_TOKEN")
    if env_agent_shared is not None:
        auth_section["shared_token"] = env_agent_shared
    env_server_shared = os.environ.get("DOPILOT_SERVER_SHARED_TOKEN")
    if env_server_shared is not None:
        agent_section["server_shared_token"] = env_server_shared

    admin_secret = (os.environ.get("DOPILOT_ADMIN_API_SECRET") or "").strip()
    if admin_secret:
        if not str(auth_section.get("shared_token") or "").strip():
            auth_section["shared_token"] = admin_secret
        if not str(agent_section.get("server_shared_token") or "").strip():
            agent_section["server_shared_token"] = admin_secret

    if not agent_section.get("agent_id"):
        raise ConfigError("missing required setting: [agent].agent_id")

    return Settings(
        agent=AgentSettings(**agent_section),
        auth=AuthSettings(**auth_section),
        capabilities=Capabilities(**cap_section),
        scrapyd=ScrapydSettings(**scrapyd_section),
        redis=RedisSettings(**redis_section),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings dependency.

    Tests override this via FastAPI ``app.dependency_overrides`` so they don't
    need a real config file on disk.
    """
    return load_settings()
