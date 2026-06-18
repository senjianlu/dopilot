"""SEAM: ``LogSource``.

One of the three phase-0/1 "abstract-first" seams. A ``LogSource`` knows how to
fetch a byte range of one log stream (it backs the server-side pull loop and,
later, the server->web SSE push). Phase 1 implements the concrete agent-pull
source; phase 0 only defines the contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dopilot_protocol import TailRequest, TailResponse

from ..clients.agent import AgentClient


class LogSource(ABC):
    """Abstract source of incremental log content for one execution stream."""

    @abstractmethod
    async def tail(self, req: TailRequest) -> TailResponse:
        """Return the byte range described by ``req`` plus EOF/finished flags."""
        raise NotImplementedError


class AgentTailLogSource(LogSource):
    """Concrete :class:`LogSource` that pulls a byte range from an agent.

    The transport is server-driven pull (decision #11): ``tail`` simply
    forwards the request to the agent's ``GET /logs/tail`` for one ``endpoint``.
    """

    def __init__(self, agent_client: AgentClient, endpoint: str) -> None:
        self._client = agent_client
        self._endpoint = endpoint

    async def tail(self, req: TailRequest) -> TailResponse:
        return await self._client.tail(self._endpoint, req)
