"""Agent status-event publisher (phase 1.5).

Builds and publishes :class:`AgentEvent`s to the shared server event stream. The
basic publisher here XADDs directly; phase 1.5 step 7 wraps :meth:`emit` with a
durable on-disk outbox + replay so state events are at-least-once.

``republish_current`` re-derives and re-emits an attempt's current event from
its local state file (idempotent re-delivery, pending recovery, restart
reconcile) — terminal results are replayed from the recorded ``result`` so the
agent never re-runs a finished attempt, and a still-``started`` attempt resolves
live via the runner. It never finalizes on ``unknown`` (re-emits ``running``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dopilot_protocol import (
    EVENT_STREAM,
    AgentEvent,
    AgentEventType,
    AttemptStatus,
    LostReason,
    to_stream_entry,
)

from ..runners.scrapyd import ScrapyRunner
from ..state.store import StateStore

logger = logging.getLogger(__name__)

# Live scrapyd status -> agent-authoritative terminal event (others are running).
_STATUS_TO_TERMINAL = {
    AttemptStatus.finished: AgentEventType.finished,
    AttemptStatus.failed: AgentEventType.failed,
    AttemptStatus.canceled: AgentEventType.canceled,
}

# Recorded local terminal result -> event type.
_RESULT_TO_EVENT = {
    "finished": AgentEventType.finished,
    "failed": AgentEventType.failed,
    "canceled": AgentEventType.canceled,
    "lost": AgentEventType.lost,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EventPublisher:
    """Publishes agent status events to ``dopilot:server:agent-events``."""

    def __init__(
        self,
        *,
        redis: object,
        agent_id: str,
        runner: ScrapyRunner,
        store: StateStore,
        maxlen_events: int = 100000,
        outbox_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._redis = redis
        self._agent_id = agent_id
        self._runner = runner
        self._store = store
        self._maxlen = maxlen_events
        self._outbox_dir = Path(outbox_dir) if outbox_dir else None

    # --- durable emit (at-least-once via on-disk outbox) -------------------
    def _persist(self, event: AgentEvent) -> Path | None:
        if self._outbox_dir is None:
            return None
        self._outbox_dir.mkdir(parents=True, exist_ok=True)
        final = self._outbox_dir / f"{event.event_id}.json"
        tmp = final.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(event.model_dump_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        return final

    async def emit(self, event: AgentEvent) -> None:
        """Publish an event. With an outbox configured, an XADD failure leaves
        the event durably queued for :meth:`replay_outbox` (never lost); without
        one, the failure propagates."""
        path = self._persist(event)
        try:
            await self._redis.xadd(
                EVENT_STREAM, to_stream_entry(event),
                maxlen=self._maxlen, approximate=True,
            )
        except Exception:  # noqa: BLE001 - Redis unavailable
            if path is None:
                raise
            logger.warning("event XADD failed; queued in outbox: %s", event.event_id)
            return
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def replay_outbox(self) -> int:
        """Re-publish any durably-queued events (server dedups/monotonic-applies).

        Order is not required: the server's monotonic state machine + event
        dedupe converge regardless of replay order (refactor/00 §状态事件可靠性)."""
        if self._outbox_dir is None or not self._outbox_dir.is_dir():
            return 0
        replayed = 0
        for entry in sorted(self._outbox_dir.glob("*.json")):
            try:
                event = AgentEvent.model_validate_json(
                    entry.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                entry.unlink(missing_ok=True)  # corrupt -> drop
                continue
            try:
                await self._redis.xadd(
                    EVENT_STREAM, to_stream_entry(event),
                    maxlen=self._maxlen, approximate=True,
                )
            except Exception:  # noqa: BLE001 - still down, leave for next pass
                break
            entry.unlink(missing_ok=True)
            replayed += 1
        return replayed

    def _event(
        self,
        *,
        execution_id: str,
        attempt_id: str,
        type: AgentEventType,
        remote_job_id: str | None = None,
        exit_code: int | None = None,
        error_code: str | None = None,
        error_detail: dict[str, Any] | None = None,
        lost_reason: LostReason | None = None,
    ) -> AgentEvent:
        return AgentEvent(
            event_id=uuid.uuid4().hex,
            agent_id=self._agent_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            type=type,
            remote_job_id=remote_job_id,
            exit_code=exit_code,
            error_code=error_code,
            error_detail=error_detail or {},
            lost_reason=lost_reason,
            created_at=_now(),
        )

    # --- convenience emits -------------------------------------------------
    async def emit_accepted(self, execution_id: str, attempt_id: str) -> None:
        await self.emit(
            self._event(
                execution_id=execution_id,
                attempt_id=attempt_id,
                type=AgentEventType.accepted,
            )
        )

    async def emit_running(
        self, execution_id: str, attempt_id: str, remote_job_id: str | None = None
    ) -> None:
        await self.emit(
            self._event(
                execution_id=execution_id,
                attempt_id=attempt_id,
                type=AgentEventType.running,
                remote_job_id=remote_job_id,
            )
        )

    async def emit_terminal(
        self,
        execution_id: str,
        attempt_id: str,
        event_type: AgentEventType,
        *,
        exit_code: int | None = None,
        error_code: str | None = None,
        error_detail: dict[str, Any] | None = None,
        lost_reason: LostReason | None = None,
    ) -> None:
        await self.emit(
            self._event(
                execution_id=execution_id,
                attempt_id=attempt_id,
                type=event_type,
                exit_code=exit_code,
                error_code=error_code,
                error_detail=error_detail,
                lost_reason=lost_reason,
            )
        )

    # --- republish from local state ---------------------------------------
    async def republish_current(self, execution_id: str, attempt_id: str) -> None:
        """Re-emit an attempt's current event from its local state file."""
        state = self._store.read(attempt_id)
        if state is None:
            await self.emit_terminal(
                execution_id, attempt_id, AgentEventType.lost,
                lost_reason=LostReason.state_missing,
            )
            return
        if state.phase == "reserved":
            # reserved but never spawned -> startup orphan
            await self.emit_terminal(
                execution_id, attempt_id, AgentEventType.failed,
                error_code="spawn_aborted", lost_reason=LostReason.spawn_aborted,
            )
            return
        if state.phase == "done" and state.result in _RESULT_TO_EVENT:
            lost_reason = (
                LostReason(state.lost_reason)
                if state.lost_reason in {r.value for r in LostReason}
                else None
            )
            await self.emit_terminal(
                execution_id,
                attempt_id,
                _RESULT_TO_EVENT[state.result],
                exit_code=state.exit_code,
                error_code=state.error_code,
                lost_reason=lost_reason,
            )
            return
        # started: resolve live status, never finalize on unknown.
        resp = await self._runner.status(attempt_id, execution_id)
        terminal = _STATUS_TO_TERMINAL.get(resp.status)
        if terminal is not None:
            await self.emit_terminal(
                execution_id, attempt_id, terminal, exit_code=resp.exit_code
            )
        else:
            await self.emit_running(
                execution_id, attempt_id, remote_job_id=state.scrapyd_job_id or None
            )
