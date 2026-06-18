"""Server -> agent HTTP client.

Wraps the agent's stateless root API (run/stop/status/logs.tail/cleanup/egg).
The server is the offset authority; this client just carries requests and
parses the protocol responses. Outgoing requests carry
``Authorization: Bearer <shared_token>`` when the agent shared token is set.

Failures are surfaced as two exception kinds so the API layer (which wants a
clean ``ApiError``) and the reconcile loop (which wants to distinguish
transient unreachable from a real agent error) can react differently:

- :class:`AgentUnreachableError` — network/timeout (retryable);
- :class:`AgentResponseError` — the agent answered with a non-2xx envelope.
"""

from __future__ import annotations

from typing import Any

import httpx
from dopilot_protocol import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentStopRequest,
    AgentStopResponse,
    CleanupResponse,
    EggDeployResponse,
    TailRequest,
    TailResponse,
)
from fastapi import Request

from ..errors import ApiError

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def normalize_endpoint(endpoint: str) -> str:
    """Return a base URL for an agent endpoint (assume http:// when no scheme)."""
    if endpoint.startswith(("http://", "https://")):
        return endpoint.rstrip("/")
    return f"http://{endpoint.rstrip('/')}"


class AgentUnreachableError(Exception):
    """The agent could not be reached (connect/timeout/transport error)."""

    def __init__(self, endpoint: str, detail: str) -> None:
        super().__init__(f"agent unreachable: {endpoint}: {detail}")
        self.endpoint = endpoint
        self.detail = detail

    def to_api_error(self) -> ApiError:
        return ApiError(
            502,
            "agent.unreachable",
            "errors.agentUnreachable",
            {"endpoint": self.endpoint, "detail": self.detail},
        )


class AgentResponseError(Exception):
    """The agent answered with a non-2xx response (carries its envelope)."""

    def __init__(self, endpoint: str, status_code: int, body: dict[str, Any]) -> None:
        super().__init__(f"agent error {status_code} from {endpoint}")
        self.endpoint = endpoint
        self.status_code = status_code
        self.body = body

    def to_api_error(self) -> ApiError:
        code = self.body.get("code") or "agent.error"
        message_key = self.body.get("message_key") or "errors.agentError"
        detail = self.body.get("detail") if isinstance(self.body.get("detail"), dict) else {}
        return ApiError(
            502,
            code if isinstance(code, str) else "agent.error",
            message_key if isinstance(message_key, str) else "errors.agentError",
            {"endpoint": self.endpoint, "agent_status": self.status_code, **detail},
        )


class AgentClient:
    """Thin async client over the agent root API for one or many endpoints."""

    def __init__(
        self, http: httpx.AsyncClient, shared_token: str | None = None
    ) -> None:
        self._http = http
        self._token = shared_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def _request(
        self, method: str, endpoint: str, path: str, **kw: Any
    ) -> httpx.Response:
        url = f"{normalize_endpoint(endpoint)}{path}"
        headers = {**self._headers(), **kw.pop("headers", {})}
        try:
            resp = await self._http.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as exc:  # connect/timeout/transport
            raise AgentUnreachableError(endpoint, str(exc)) from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = {"detail": {"raw": resp.text[:500]}}
            raise AgentResponseError(endpoint, resp.status_code, body or {})
        return resp

    async def run(
        self, endpoint: str, req: AgentRunRequest
    ) -> AgentRunResponse:
        resp = await self._request(
            "POST", endpoint, "/run", json=req.model_dump(mode="json")
        )
        return AgentRunResponse.model_validate(resp.json())

    async def stop(
        self, endpoint: str, req: AgentStopRequest
    ) -> AgentStopResponse:
        resp = await self._request(
            "POST", endpoint, "/stop", json=req.model_dump(mode="json")
        )
        return AgentStopResponse.model_validate(resp.json())

    async def status(
        self, endpoint: str, execution_id: str, attempt_id: str
    ) -> AgentStatusResponse:
        resp = await self._request(
            "GET",
            endpoint,
            "/status",
            params={"execution_id": execution_id, "attempt_id": attempt_id},
        )
        return AgentStatusResponse.model_validate(resp.json())

    async def tail(self, endpoint: str, req: TailRequest) -> TailResponse:
        resp = await self._request(
            "GET",
            endpoint,
            "/logs/tail",
            params={
                "execution_id": req.execution_id,
                "attempt_id": req.attempt_id,
                "stream": req.stream.value,
                "offset": req.offset,
                "max_bytes": req.max_bytes,
            },
        )
        return TailResponse.model_validate(resp.json())

    async def cleanup(
        self,
        endpoint: str,
        attempt_id: str,
        execution_id: str | None = None,
        stream: str = "log",
    ) -> CleanupResponse:
        resp = await self._request(
            "POST",
            endpoint,
            f"/executions/{attempt_id}/logs/cleanup",
            json={"execution_id": execution_id, "stream": stream},
        )
        return CleanupResponse.model_validate(resp.json())

    async def deploy_egg(
        self,
        endpoint: str,
        project: str,
        version: str,
        filename: str,
        egg_bytes: bytes,
    ) -> EggDeployResponse:
        resp = await self._request(
            "POST",
            endpoint,
            "/artifacts/scrapy/egg",
            data={"project": project, "version": version},
            files={"file": (filename, egg_bytes, "application/octet-stream")},
        )
        return EggDeployResponse.model_validate(resp.json())


def get_agent_client(request: Request) -> AgentClient:
    """FastAPI dependency returning the app-wide :class:`AgentClient`.

    Built in ``create_app`` and stored on ``app.state``; tests override this
    dependency to inject an :class:`AgentClient` backed by an httpx
    ``MockTransport`` (no real agent needed).
    """
    client = getattr(request.app.state, "agent_client", None)
    if client is None:  # pragma: no cover - defensive
        raise ApiError(
            500,
            "server.agent_client_unconfigured",
            "errors.internal",
            {},
        )
    return client
