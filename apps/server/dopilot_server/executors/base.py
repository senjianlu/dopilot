"""SEAM: ``BaseExecutor`` + ``ExecutorContext``.

One of the three phase-0/1 "abstract-first" seams. All three scheduled-object
types (scrapy/script/docker) implement this single interface so dispatch code
is written once. Phase 1.5 evolves the seam to dispatch over the Redis command
stream: the context carries the :class:`CommandDispatcher` (which owns the
command producer + outbox try_dispatch) instead of an HTTP agent client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..redis.dispatcher import CommandDispatcher
from ..services.executions import TaskOrigin


class DispatchUnknownError(Exception):
    """The ``run`` command was XADDed to Redis but the ``sent`` mark failed to
    commit. The command may already be running on the agent, so the API must
    NOT report "not delivered" — it returns 202 ``dispatch_unknown`` and the
    agent's ``attempt.running`` event converges the execution (refactor/00)."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"dispatch result unknown for execution {execution_id}")
        self.execution_id = execution_id


@dataclass
class ExecutorContext:
    """Per-request dependencies handed to an executor's :meth:`run`."""

    session: AsyncSession
    settings: Settings
    dispatcher: CommandDispatcher


class BaseExecutor(ABC):
    """Abstract runner for one scheduled-object type.

    Subclasses set :attr:`task_type` (e.g. ``"scrapy"``) and implement
    :meth:`run`.
    """

    task_type: str = ""

    @abstractmethod
    async def run(
        self,
        request: ExecutionRunRequest,
        ctx: ExecutorContext,
        origin: TaskOrigin | None = None,
    ) -> ExecutionRunResponse:
        """Dispatch ``request`` and return the created task handle.

        ``origin`` records provenance (manual / schedule_trigger_now /
        schedule_timer) + the immutable template snapshot copied into the task.
        """
        raise NotImplementedError
