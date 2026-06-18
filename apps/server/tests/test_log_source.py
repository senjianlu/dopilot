"""Tests for the LogSource seam (AgentTailLogSource)."""

from __future__ import annotations

from dopilot_protocol import TailRequest, TailResponse
from dopilot_server.logs.source import AgentTailLogSource


class _RecordingClient:
    def __init__(self) -> None:
        self.seen = None

    async def tail(self, endpoint, req) -> TailResponse:
        self.seen = (endpoint, req)
        return TailResponse(
            start_offset=req.offset,
            end_offset=req.offset + 3,
            content="abc",
            eof=True,
            finished=True,
        )


async def test_agent_tail_log_source_delegates():
    client = _RecordingClient()
    source = AgentTailLogSource(client, "http://agent:6800")
    resp = await source.tail(
        TailRequest(execution_id="e1", attempt_id="a1", offset=10)
    )
    assert resp.content == "abc"
    assert resp.start_offset == 10 and resp.end_offset == 13
    endpoint, req = client.seen
    assert endpoint == "http://agent:6800"
    assert req.execution_id == "e1" and req.attempt_id == "a1"
