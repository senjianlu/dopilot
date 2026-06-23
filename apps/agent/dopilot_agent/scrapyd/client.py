"""Async HTTP client for the local scrapyd JSON API.

Wraps the handful of scrapyd endpoints the agent needs:
``addversion.json`` / ``schedule.json`` / ``cancel.json`` / ``listjobs.json``.
Every scrapyd response is a JSON object with a ``status`` field that is
``"ok"`` or ``"error"``; a non-ok status (or a transport failure) is surfaced
as :class:`ScrapydError` so the API layer can translate it into the frozen
``ErrorResponse`` envelope.

The client is constructed from a base URL (``http://127.0.0.1:6801`` in
production) and an optional httpx transport, which lets tests inject an
``httpx.MockTransport``-backed fake scrapyd — no real scrapyd binary required.
"""

from __future__ import annotations

from typing import Any

import httpx


class ScrapydError(Exception):
    """A scrapyd call failed (transport error or ``status != ok``)."""

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict[str, Any] = detail if detail is not None else {}


class ScrapydClient:
    """Thin async client over the local scrapyd JSON API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:6801",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=self._timeout,
        )

    async def _post(
        self,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._client() as client:
                resp = await client.post(path, data=data, files=files)
        except httpx.HTTPError as exc:
            raise ScrapydError(
                f"scrapyd request failed: {exc}", detail={"path": path}
            ) from exc
        return self._parse(path, resp)

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with self._client() as client:
                resp = await client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ScrapydError(
                f"scrapyd request failed: {exc}", detail={"path": path}
            ) from exc
        return self._parse(path, resp)

    @staticmethod
    def _parse(path: str, resp: httpx.Response) -> dict[str, Any]:
        try:
            body: Any = resp.json()
        except ValueError as exc:
            raise ScrapydError(
                f"scrapyd returned non-JSON for {path}",
                detail={"path": path, "http_status": resp.status_code},
            ) from exc
        if not isinstance(body, dict):
            raise ScrapydError(
                f"scrapyd returned unexpected payload for {path}",
                detail={"path": path},
            )
        if body.get("status") != "ok":
            raise ScrapydError(
                body.get("message", f"scrapyd status != ok for {path}"),
                detail={"path": path, "scrapyd": body},
            )
        return body

    async def addversion(
        self, project: str, version: str, egg_bytes: bytes
    ) -> dict[str, Any]:
        """Deploy a pre-built egg; returns scrapyd's addversion response."""
        return await self._post(
            "/addversion.json",
            data={"project": project, "version": version},
            files={"egg": ("project.egg", egg_bytes, "application/octet-stream")},
        )

    async def schedule(
        self,
        project: str,
        spider: str,
        *,
        version: str | None = None,
        settings: dict[str, str] | None = None,
        args: dict[str, str] | None = None,
    ) -> str:
        """Schedule a spider run; returns the scrapyd job id."""
        data: dict[str, Any] = {"project": project, "spider": spider}
        if version:
            data["_version"] = version
        # scrapyd expects repeated `setting=KEY=VALUE` form fields.
        if settings:
            data["setting"] = [f"{k}={v}" for k, v in settings.items()]
        if args:
            for key, value in args.items():
                data[key] = value
        body = await self._post("/schedule.json", data=data)
        jobid = body.get("jobid")
        if not jobid:
            raise ScrapydError(
                "scrapyd schedule returned no jobid",
                detail={"scrapyd": body},
            )
        return str(jobid)

    async def cancel(self, project: str, job: str) -> dict[str, Any]:
        """Cancel a job; returns scrapyd's cancel response (``prevstate``)."""
        return await self._post(
            "/cancel.json", data={"project": project, "job": job}
        )

    async def listjobs(self, project: str) -> dict[str, Any]:
        """Return scrapyd's pending/running/finished job lists for a project."""
        return await self._get("/listjobs.json", params={"project": project})

    async def daemonstatus(self) -> dict[str, Any]:
        """Return scrapyd's ``daemonstatus.json`` (raises if unreachable / != ok).

        Used by the agent container healthcheck to verify the local scrapyd the
        agent manages is answering on its container-internal port.
        """
        return await self._get("/daemonstatus.json")
