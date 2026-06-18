"""Agent settings models (Pydantic v2).

These mirror the agent-side TOML config. The agent never connects to a
database; it only knows about itself (id/host/port/workdir), its shared-token
auth, and which capabilities it advertises.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    """Identity and HTTP bind settings for this agent."""

    agent_id: str
    host: str = "0.0.0.0"
    port: int = 6800
    workdir: str = "/agent-data"


class AuthSettings(BaseModel):
    """Server->agent shared-token auth.

    Auth is enabled iff ``shared_token`` is non-empty.
    """

    shared_token: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.shared_token)


class Capabilities(BaseModel):
    """Which scheduled-object types this agent can execute.

    Field shape matches the frozen ``CapabilitySet`` protocol contract.
    """

    scrapy: bool = False
    script: bool = False
    docker: bool = False


class ScrapydSettings(BaseModel):
    """Local scrapyd subprocess settings.

    The agent owns a scrapyd child bound to ``host:port`` on a container-internal
    address (never exposed to the host). Its data dirs live under
    ``{workdir}/scrapyd``. ``start=False`` lets a deployment point the agent at an
    externally managed scrapyd (and skips spawning a child) — the default is to
    spawn one.
    """

    start: bool = True
    host: str = "127.0.0.1"
    port: int = 6801


class Settings(BaseModel):
    """Top-level agent settings."""

    agent: AgentSettings
    auth: AuthSettings = Field(default_factory=AuthSettings)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    scrapyd: ScrapydSettings = Field(default_factory=ScrapydSettings)
