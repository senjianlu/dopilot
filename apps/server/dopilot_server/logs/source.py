"""SEAM: ``LogSource``.

One of the three phase-0/1 "abstract-first" seams. A ``LogSource`` knows how to
fetch a byte range of one log stream (it backs the server-side pull loop and,
later, the server->web SSE push). Phase 1 implements the concrete agent-pull
source; phase 0 only defines the contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dopilot_protocol import TailRequest, TailResponse


class LogSource(ABC):
    """Abstract source of incremental log content for one execution stream."""

    @abstractmethod
    async def tail(self, req: TailRequest) -> TailResponse:
        """Return the byte range described by ``req`` plus EOF/finished flags."""
        raise NotImplementedError
