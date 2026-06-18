"""SEAM: ``BaseExecutor`` + ``ExecutorContext``.

One of the three phase-0/1 "abstract-first" seams. All three scheduled-object
types (scrapy/script/docker) implement this single interface so dispatch code
is written once. Phase 1 evolves the seam to take an :class:`ExecutorContext`
(session + settings + agent client) so executors stay stateless and testable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..clients.agent import AgentClient
from ..config.settings import Settings


@dataclass
class ExecutorContext:
    """Per-request dependencies handed to an executor's :meth:`run`."""

    session: AsyncSession
    settings: Settings
    agent_client: AgentClient


class BaseExecutor(ABC):
    """Abstract runner for one scheduled-object type.

    Subclasses set :attr:`task_type` (e.g. ``"scrapy"``) and implement
    :meth:`run`.
    """

    task_type: str = ""

    @abstractmethod
    async def run(
        self, request: ExecutionRunRequest, ctx: ExecutorContext
    ) -> ExecutionRunResponse:
        """Dispatch ``request`` and return the created execution handle."""
        raise NotImplementedError
