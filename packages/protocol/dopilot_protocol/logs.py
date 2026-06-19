"""Log tail protocol: stream selector plus pull request/response envelopes.

:class:`LogStream` is shared and current. :class:`TailRequest` /
:class:`TailResponse` are **LEGACY** (phase-1 server-pull tail contract):
phase 1.5 replaces server pull with agent-pushed log increments over a Redis
stream — see :class:`dopilot_protocol.streams.AgentLogEvent`. They are kept only
until the phase-1 HTTP tail path is removed.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class LogStream(str, Enum):
    """Which log stream of an execution attempt to tail."""

    log = "log"
    stdout = "stdout"
    stderr = "stderr"
    system = "system"


class TailRequest(BaseModel):
    """Server -> agent request to read a byte slice of an attempt's log."""

    execution_id: str
    attempt_id: str
    stream: LogStream = LogStream.log
    offset: int = 0
    max_bytes: int = 262144


class TailResponse(BaseModel):
    """Agent -> server response carrying the read slice and tail state."""

    start_offset: int
    end_offset: int
    content: str
    eof: bool
    finished: bool
