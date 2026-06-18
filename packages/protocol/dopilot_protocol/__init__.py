"""dopilot shared protocol: server<->agent Pydantic v2 schemas.

This package is dependency-free of dopilot_server / dopilot_agent; the
dependency direction is one-way (server and agent depend on protocol).
"""

from __future__ import annotations

from .agent import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentStopRequest,
    AgentStopResponse,
    AttemptStatus,
    CleanupResponse,
    EggDeployResponse,
)
from .common import CapabilitySet, ErrorResponse
from .execution import ExecutionRunRequest, ExecutionRunResponse
from .health import HealthResponse
from .logs import LogStream, TailRequest, TailResponse

__version__ = "0.0.0"

__all__ = [
    "CapabilitySet",
    "ErrorResponse",
    "HealthResponse",
    "LogStream",
    "TailRequest",
    "TailResponse",
    "ExecutionRunRequest",
    "ExecutionRunResponse",
    # server -> agent execution control (phase 1)
    "AttemptStatus",
    "AgentRunRequest",
    "AgentRunResponse",
    "AgentStopRequest",
    "AgentStopResponse",
    "AgentStatusResponse",
    "CleanupResponse",
    "EggDeployResponse",
    "__version__",
]
