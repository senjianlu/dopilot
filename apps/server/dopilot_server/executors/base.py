"""SEAM: ``BaseExecutor``.

One of the three phase-0/1 "abstract-first" seams. All three scheduled-object
types (scrapy/script/docker) implement this single interface so dispatch code
is written once. Phase 0 only defines the abstract contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse


class BaseExecutor(ABC):
    """Abstract runner for one scheduled-object type.

    Subclasses set :attr:`task_type` (e.g. ``"scrapy"``) and implement
    :meth:`run`.
    """

    task_type: str = ""

    @abstractmethod
    async def run(self, request: ExecutionRunRequest) -> ExecutionRunResponse:
        """Dispatch ``request`` and return the created execution handle."""
        raise NotImplementedError
