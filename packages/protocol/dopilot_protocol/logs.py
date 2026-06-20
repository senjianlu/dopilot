"""Log stream selector shared by server and agent.

:class:`LogStream` is shared and current. The phase-1 server-pull tail
request/response envelopes were removed in phase 2a — phase 1.5 replaced server
pull with agent-pushed log increments over a Redis stream
(:class:`dopilot_protocol.streams.AgentLogEvent`).
"""

from __future__ import annotations

from enum import Enum


class LogStream(str, Enum):
    """Which log stream of an execution attempt to tail."""

    log = "log"
    stdout = "stdout"
    stderr = "stderr"
    system = "system"
