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


class Settings(BaseModel):
    """Top-level agent settings."""

    agent: AgentSettings
    auth: AuthSettings = Field(default_factory=AuthSettings)
    capabilities: Capabilities = Field(default_factory=Capabilities)
