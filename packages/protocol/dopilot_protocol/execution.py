"""Execution dispatch protocol: run request/response for server -> agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecutionRunRequest(BaseModel):
    """Request to run a scheduled object on one or more nodes."""

    task_type: str
    target: str
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ExecutionRunResponse(BaseModel):
    """Response acknowledging a dispatched execution."""

    execution_id: str
    status: str
