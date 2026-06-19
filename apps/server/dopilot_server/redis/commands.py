"""Command producer (phase 1.5): XADD a command to a per-agent command stream."""

from __future__ import annotations

from dopilot_protocol import AgentCommand, command_stream, to_stream_entry

from ..config.settings import RedisSettings


def msg_id_to_str(msg_id: object) -> str:
    """Normalize a Redis stream message id (bytes or str) to str."""
    if isinstance(msg_id, bytes):
        return msg_id.decode("utf-8")
    return str(msg_id)


class CommandProducer:
    """Writes commands to ``dopilot:agent:{agent_id}:commands`` (MAXLEN ~)."""

    def __init__(self, redis: object, settings: RedisSettings) -> None:
        self._redis = redis
        self._maxlen = settings.stream_maxlen_commands

    async def send(self, cmd: AgentCommand) -> str:
        """XADD ``cmd`` to its agent's command stream; return the message id."""
        stream = command_stream(cmd.agent_id)
        msg_id = await self._redis.xadd(
            stream, to_stream_entry(cmd), maxlen=self._maxlen, approximate=True
        )
        return msg_id_to_str(msg_id)
