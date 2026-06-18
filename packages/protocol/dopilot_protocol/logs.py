"""Log tail protocol: stream selector plus pull request/response envelopes.

dopilot realtime logs are server-pull (decision #11): the server pulls log
increments from the agent tail API. These schemas describe that pull contract.
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
