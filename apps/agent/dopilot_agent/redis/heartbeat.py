"""Agent heartbeat worker (phase 1.5).

Periodically POSTs ``/api/v1/agents/{agent_id}/heartbeat`` to the server with
the agent's liveness, capabilities, load, and advertised endpoint. This is the
agent-initiated health signal that replaces the server polling agent ``/health``.
Heartbeat goes over HTTP (NOT Redis) and carries the dedicated agent -> server
token.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from dopilot_protocol import AgentHeartbeatRequest, CapabilitySet

from ..config.settings import Settings
from ..state.store import StateStore
from .status import RedisRuntimeStatus

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class HeartbeatWorker:
    """Background task that reports agent liveness to the server."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: StateStore,
        version: str,
        client: httpx.AsyncClient | None = None,
        redis_status: RedisRuntimeStatus | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._version = version
        self._client = client
        self._redis_status = redis_status
        self._owns_client = client is None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # --- payload -----------------------------------------------------------
    def build_request(self) -> AgentHeartbeatRequest:
        s = self._settings
        caps = CapabilitySet(
            scrapy=s.capabilities.scrapy,
            script=s.capabilities.script,
            docker=s.capabilities.docker,
        )
        running = len(self._store.list_execution_ids())
        detail = {
            "scrapyd": {
                "port": s.scrapyd.port,
                "managed": s.scrapyd.start,
            }
        }
        if self._redis_status is not None:
            detail["redis"] = self._redis_status.snapshot()
        return AgentHeartbeatRequest(
            agent_id=s.agent.agent_id,
            version=self._version,
            capabilities=caps,
            load={"running_attempts": running},
            detail=detail,
            endpoint=s.agent.advertise_endpoint or None,
            reported_at=datetime.now(UTC).isoformat(),
        )

    def _url(self) -> str:
        base = self._settings.agent.server_url.rstrip("/")
        return f"{base}/api/v1/agents/{self._settings.agent.agent_id}/heartbeat"

    def _headers(self) -> dict[str, str]:
        token = self._settings.agent.server_shared_token
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def send_once(self, http: httpx.AsyncClient) -> bool:
        """Send one heartbeat. Returns True on a 2xx response."""
        req = self.build_request()
        resp = await http.post(
            self._url(), json=req.model_dump(), headers=self._headers()
        )
        return resp.status_code < 300

    # --- loop --------------------------------------------------------------
    async def _run(self) -> None:
        interval = max(1, self._settings.agent.heartbeat_interval_seconds)
        client = self._client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        try:
            while not self._stop.is_set():
                try:
                    await self.send_once(client)
                except Exception:  # noqa: BLE001 - never let the loop die
                    logger.warning("heartbeat send failed", exc_info=True)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except TimeoutError:
                    pass
        finally:
            if self._owns_client:
                await client.aclose()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
