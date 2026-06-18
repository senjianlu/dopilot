"""Execution dispatch protocol: run request/response for server -> agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecutionRunRequest(BaseModel):
    """Request to run a scheduled object on one or more nodes (web -> server).

    ``task_type`` selects the executor (phase 1: only ``"scrapy"``). ``target``
    is a human-facing label for the run. Type-specific inputs live in
    ``params``; for ``task_type="scrapy"`` the server reads:

    - ``params["project"]`` (str, required) — deployed scrapyd project,
    - ``params["spider"]`` (str, required) — spider name to run,
    - ``params["version"]`` (str, optional) — deployed egg version,
    - ``params["settings"]`` (dict[str, str], optional) — scrapyd settings,
    - ``params["args"]`` (dict[str, str], optional) — spider arguments.

    ``node_strategy`` is one of ``all`` / ``random`` / ``selected``; for
    ``selected`` the chosen stable agent/node ids go in ``node_ids``.
    """

    task_type: str
    target: str
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ExecutionRunResponse(BaseModel):
    """Response acknowledging a dispatched execution."""

    execution_id: str
    status: str
