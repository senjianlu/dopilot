"""Execution dispatch protocol: run request/response for server -> agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecutionRunRequest(BaseModel):
    """Internal resolved run request handed to an executor (phase 1.8).

    ``artifact_type`` is the core-domain discriminator selecting the executor
    (phase 1.8: only ``"scrapy"`` is runnable). It is translated to the wire
    ``task_type`` only in the Redis command payload, at the dispatcher boundary.
    ``target`` is a human-facing label. Type-specific inputs live in ``params``;
    for ``artifact_type="scrapy"`` the server reads:

    - ``params["project"]`` (str, required) — deployed scrapyd project,
    - ``params["spider"]`` (str, required) — spider name to run,
    - ``params["version"]`` (str, optional) — deployed egg version,
    - ``params["settings"]`` (dict[str, str], optional) — scrapyd settings,
    - ``params["args"]`` (dict[str, str], optional) — spider arguments.

    ``node_strategy`` is one of ``all`` / ``random`` / ``selected``; for
    ``selected`` the chosen stable agent/node ids go in ``node_ids``.
    """

    artifact_type: str
    target: str
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ExecutionRunResponse(BaseModel):
    """Response acknowledging a dispatched run. ``task_id`` is the parent task."""

    task_id: str
    status: str
