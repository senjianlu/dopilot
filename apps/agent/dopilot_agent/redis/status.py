"""Runtime Redis transport health reported in agent heartbeats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RedisRuntimeStatus:
    """Small shared status object updated by Redis workers."""

    connected: bool = False
    last_ok_at: str | None = None
    last_error: str | None = None
    command_consumer_running: bool = False
    command_consumer_last_read_at: str | None = None
    event_outbox_pending: int = 0
    log_publisher_running: bool = False
    log_publisher_last_publish_at: str | None = None

    def mark_ok(self) -> None:
        self.connected = True
        self.last_ok_at = _now()
        self.last_error = None

    def mark_error(self, exc: BaseException) -> None:
        self.connected = False
        self.last_error = f"{type(exc).__name__}: {exc}"

    def mark_command_running(self, running: bool) -> None:
        self.command_consumer_running = running

    def mark_command_read(self) -> None:
        self.command_consumer_last_read_at = _now()
        self.mark_ok()

    def mark_event_outbox_pending(self, pending: int) -> None:
        self.event_outbox_pending = pending

    def mark_log_running(self, running: bool) -> None:
        self.log_publisher_running = running

    def mark_log_publish(self) -> None:
        self.log_publisher_last_publish_at = _now()
        self.mark_ok()

    def snapshot(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "last_ok_at": self.last_ok_at,
            "last_error": self.last_error,
            "command_consumer": {
                "running": self.command_consumer_running,
                "last_read_at": self.command_consumer_last_read_at,
            },
            "event_outbox": {
                "pending": self.event_outbox_pending,
            },
            "log_publisher": {
                "running": self.log_publisher_running,
                "last_publish_at": self.log_publisher_last_publish_at,
            },
        }
