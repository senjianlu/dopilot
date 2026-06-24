"""Execution dispatch protocol: run request/response for server -> agent."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

_RUNTIME_CONTEXT_ENV_KEYS = {
    "task_id": "DOPILOT_TASK_ID",
    "execution_id": "DOPILOT_EXECUTION_ID",
    "agent_id": "DOPILOT_AGENT_ID",
    "artifact_type": "DOPILOT_ARTIFACT_TYPE",
    "task_type": "DOPILOT_TASK_TYPE",
    "source": "DOPILOT_TASK_SOURCE",
    "execution_template_id": "DOPILOT_EXECUTION_TEMPLATE_ID",
    "schedule_id": "DOPILOT_SCHEDULE_ID",
}


class DopilotRuntimeContext(BaseModel):
    """Canonical per-run context exposed to user workloads.

    Individual carrier keys use empty strings for nullable values; the compact
    JSON carrier preserves JSON nulls and is deterministic for tests/workloads.
    """

    task_id: str
    execution_id: str
    agent_id: str
    artifact_type: str
    task_type: str
    source: str
    execution_template_id: str | None = None
    schedule_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_env_map(self) -> dict[str, str]:
        values = self.model_dump(mode="json")
        mapped = {
            env_key: "" if values[field] is None else str(values[field])
            for field, env_key in _RUNTIME_CONTEXT_ENV_KEYS.items()
        }
        mapped["DOPILOT_RUNTIME_CONTEXT"] = self.to_json()
        return mapped

    def to_scrapy_settings(self) -> dict[str, str]:
        return self.to_env_map()


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
    runtime_context: DopilotRuntimeContext | None = None
    task_type: str = "scrapy"


class PythonWheelRunPayload(BaseModel):
    """The Redis ``run`` command payload for a Python-wheel task (phase 2b).

    Shell-command contract: the payload carries a free-form ``shell_command``
    (the user input lives in ``ExecutionTemplate.command`` and is serialized
    here as ``shell_command``) plus the build-artifact ``artifact`` context the
    agent needs to fetch + install the wheel. ``env`` is an optional operator
    override map (the server currently emits ``{}``); ``working_dir`` is an
    OPTIONAL relative path under the per-execution workspace (absolute paths /
    ``..`` escapes are rejected by the agent runner in packet 2b-2).

    ``task_type`` is the stable wire discriminator the agent runner branches on;
    it is deliberately distinct from the node-selection capability (``script``).
    """

    shell_command: str
    artifact: dict[str, Any] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    working_dir: str | None = None
    runtime_context: DopilotRuntimeContext | None = None
    task_type: str = "python_wheel"


class ExecutionRunResponse(BaseModel):
    """Response acknowledging a dispatched run. ``task_id`` is the parent task."""

    task_id: str
    status: str
