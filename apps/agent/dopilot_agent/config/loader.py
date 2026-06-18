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

from .settings import AgentSettings, AuthSettings, Capabilities, Settings


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


def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    """Load agent settings from TOML.

    Resolution order for the path: explicit ``path`` argument, then the
    ``DOPILOT_CONFIG`` environment variable. Environment overrides applied
    after parsing: ``AGENT_ID`` -> ``[agent].agent_id``, ``AGENT_WORKDIR`` ->
    ``[agent].workdir``.
    """
    raw_path = path if path is not None else os.environ.get("DOPILOT_CONFIG")
    if not raw_path:
        raise ConfigError(
            "no config path provided; set DOPILOT_CONFIG or pass path explicitly"
        )

    data = _read_toml(Path(raw_path))

    agent_section: dict[str, Any] = dict(data.get("agent") or {})
    auth_section: dict[str, Any] = dict(data.get("auth") or {})
    cap_section: dict[str, Any] = dict(data.get("capabilities") or {})

    env_agent_id = os.environ.get("AGENT_ID")
    if env_agent_id:
        agent_section["agent_id"] = env_agent_id
    env_workdir = os.environ.get("AGENT_WORKDIR")
    if env_workdir:
        agent_section["workdir"] = env_workdir

    if not agent_section.get("agent_id"):
        raise ConfigError("missing required setting: [agent].agent_id")

    return Settings(
        agent=AgentSettings(**agent_section),
        auth=AuthSettings(**auth_section),
        capabilities=Capabilities(**cap_section),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings dependency.

    Tests override this via FastAPI ``app.dependency_overrides`` so they don't
    need a real config file on disk.
    """
    return load_settings()
