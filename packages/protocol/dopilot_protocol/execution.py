"""Execution dispatch protocol: run request/response for server -> agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecutionRunRequest(BaseModel):
    """Internal resolved run request handed to an executor (phase 1.8.1).

    ``artifact_type`` is the core-domain discriminator selecting the executor
    (phase 1.8.1: only ``"scrapy"`` is runnable). It is translated to the wire
    ``task_type`` only in the Redis command payload, at the dispatcher boundary.
    ``target`` is a human-facing label. Type-specific inputs live in ``params``;
    for ``artifact_type="scrapy"`` dopilot is **command-first** and the server
    reads:

    - ``params["command"]`` (str, required) — the ``scrapy crawl ...`` command,
      the authoritative execution input (see :mod:`dopilot_protocol.scrapy_command`),
    - ``params["artifact"]`` (dict, required) — the build-artifact context
      (project / version / sha256 / filename / fetch_path) the agent needs to
      resolve the scrapyd project/version, since the command alone does not name
      one,
    - ``params["spider"]`` (str) — a DERIVED convenience copied from the parsed
      command (backs ``Task.spider``), NOT the execution model,
    - ``params["project"]`` / ``params["version"]`` — resolved from the artifact.

    ``node_strategy`` is one of ``all`` / ``random`` / ``selected``; for
    ``selected`` the chosen stable agent/node ids go in ``node_ids``.
    """

    artifact_type: str
    target: str
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ScrapyRunPayload(BaseModel):
    """The Redis ``run`` command payload for a Scrapy task (phase 1.8.1).

    Command-first contract: the payload carries the ``command`` string plus the
    build-artifact ``artifact`` context, NOT decomposed ``spider`` / ``settings``
    / ``args``. The agent parses ``command`` with the shared parser and resolves
    project/version from ``artifact``. ``task_type`` is the stable wire
    discriminator (kept for the seam).
    """

    command: str
    artifact: dict[str, Any] = Field(default_factory=dict)
    task_type: str = "scrapy"


class ExecutionRunResponse(BaseModel):
    """Response acknowledging a dispatched run. ``task_id`` is the parent task."""

    task_id: str
    status: str
