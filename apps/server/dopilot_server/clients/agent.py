"""Server -> agent HTTP client (phase 1.5: egg deploy ONLY).

The phase-1 run/stop/status/logs-tail/cleanup HTTP main paths were removed in the
Redis Streams refactor; the only surviving server->agent HTTP path is **egg
deploy** (``POST /artifacts/scrapy/egg`` -> agent -> local scrapyd
``/addversion.json``), which stays HTTP by design. Outgoing requests carry
``Authorization: Bearer <shared_token>`` (the server->agent token) when set.

Failures surface as two kinds so the API layer can render a clean ``ApiError``:

- :class:`AgentUnreachableError` — network/timeout (transport error);
- :class:`AgentResponseError` — the agent answered with a non-2xx envelope.
"""

from __future__ import annotations

from typing import Any

import httpx
from dopilot_protocol import EggDeployResponse
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
    """Thin async client over the agent's surviving egg-deploy HTTP endpoint."""

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
    """FastAPI dependency returning the app-wide egg-deploy :class:`AgentClient`.

    Built in the lifespan and stored on ``app.state.agent_client``; tests
    override this dependency to inject one backed by an httpx ``MockTransport``.
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
