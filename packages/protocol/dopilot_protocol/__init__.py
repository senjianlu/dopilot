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
from .execution import ExecutionRunRequest, ExecutionRunResponse, ScrapyRunPayload
from .health import HealthResponse
from .logs import LogStream, TailRequest, TailResponse
from .scrapy_command import (
    ParsedScrapyCommand,
    ScrapyCommandError,
    build_scrapy_command,
    is_valid_scrapy_command,
    parse_scrapy_command,
)
from .streams import (
    COMMAND_GROUP,
    EVENT_GROUP,
    EVENT_STREAM,
    LOG_GROUP,
    LOG_STREAM,
    AgentCommand,
    AgentCommandType,
    AgentEvent,
    AgentEventType,
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentLogEvent,
    LostReason,
    StopIntent,
    command_stream,
    from_stream_entry,
    to_stream_entry,
)

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
    "ScrapyRunPayload",
    # shared Scrapy command parser/validator (phase 1.8.1, command-first)
    "ParsedScrapyCommand",
    "ScrapyCommandError",
    "parse_scrapy_command",
    "is_valid_scrapy_command",
    "build_scrapy_command",
    # server -> agent execution control (phase 1, LEGACY HTTP path)
    "AttemptStatus",
    "AgentRunRequest",
    "AgentRunResponse",
    "AgentStopRequest",
    "AgentStopResponse",
    "AgentStatusResponse",
    "CleanupResponse",
    "EggDeployResponse",
    # Redis Streams communication (phase 1.5)
    "AgentCommand",
    "AgentCommandType",
    "StopIntent",
    "AgentEvent",
    "AgentEventType",
    "LostReason",
    "AgentLogEvent",
    "AgentHeartbeatRequest",
    "AgentHeartbeatResponse",
    "command_stream",
    "EVENT_STREAM",
    "LOG_STREAM",
    "COMMAND_GROUP",
    "EVENT_GROUP",
    "LOG_GROUP",
    "to_stream_entry",
    "from_stream_entry",
    "__version__",
]
