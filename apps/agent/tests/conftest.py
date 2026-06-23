"""Shared pytest fixtures for the agent test suite.

The agent is an outbound-only worker daemon (no FastAPI app), so the suite
exercises the runtime objects directly:

- a **fake scrapyd** (:class:`FakeScrapyd`) served via ``httpx.MockTransport``,
  wired into a real :class:`ScrapydClient` / :class:`ScrapyRunner` by
  :func:`make_runner` — no real scrapyd binary needed;
- an in-memory Redis Streams double (:class:`FakeRedisStreams`) for the command
  consumer / log publisher / event outbox tests.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import fakeredis.aioredis as fakeaioredis
import httpx
import pytest
import pytest_asyncio
from dopilot_agent.deps import scrapyd_logs_dir, state_dir
from dopilot_agent.runners.scrapyd import ScrapyRunner
from dopilot_agent.scrapyd.client import ScrapydClient
from dopilot_agent.state.store import StateStore
from redis.exceptions import ConnectionError as RedisConnectionError


class FakeScrapyd:
    """In-process stand-in for scrapyd, served via httpx.MockTransport.

    Records scheduled jobs and answers schedule/cancel/listjobs/addversion. Tests
    drive its state directly (e.g. move a job from running -> finished) to
    exercise the runner's status mapping.
    """

    def __init__(self) -> None:
        self.running: list[dict] = []
        self.finished: list[dict] = []
        self.pending: list[dict] = []
        self.deployed: dict[tuple[str, str], list[str]] = {}
        self.spiders: list[str] = ["phase1"]
        self._counter = 0
        self.fail_schedule = False
        self.fail_addversion = False
        self.fail_listjobs = False
        # Captured schedule.json submissions (project/spider/args/settings) so
        # command-first tests can assert what the agent sent to scrapyd.
        self.schedules: list[dict] = []

    # --- test-side helpers ------------------------------------------------
    def add_running(self, job_id: str, project: str, spider: str) -> None:
        self.running.append({"id": job_id, "project": project, "spider": spider})

    def move_to_finished(self, job_id: str) -> None:
        self.running = [j for j in self.running if j["id"] != job_id]
        self.pending = [j for j in self.pending if j["id"] != job_id]
        self.finished.append({"id": job_id})

    # --- mock transport ---------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/schedule.json":
            return self._schedule(request)
        if path == "/cancel.json":
            return self._cancel(request)
        if path == "/listjobs.json":
            return self._listjobs(request)
        if path == "/addversion.json":
            return self._addversion(request)
        return httpx.Response(404, json={"status": "error", "message": "not found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def _form(self, request: httpx.Request) -> dict[str, list[str]]:
        body = request.content.decode("utf-8")
        return parse_qs(body, keep_blank_values=True)

    @staticmethod
    def _first(form: dict[str, list[str]], key: str) -> str | None:
        values = form.get(key)
        return values[0] if values else None

    def _schedule(self, request: httpx.Request) -> httpx.Response:
        if self.fail_schedule:
            return httpx.Response(
                200, json={"status": "error", "message": "boom"}
            )
        form = self._form(request)
        self._counter += 1
        job_id = f"job-{self._counter:04d}"
        project = self._first(form, "project") or "?"
        spider = self._first(form, "spider") or "?"
        self.add_running(job_id, project, spider)
        # Decode scrapyd's wire form: repeated ``setting=KEY=VALUE`` for settings,
        # any other non-reserved field is a spider arg.
        reserved = {"project", "spider", "_version", "setting"}
        settings: dict[str, str] = {}
        for raw in form.get("setting", []):
            key, _, value = raw.partition("=")
            settings[key] = value
        args = {
            k: v[0]
            for k, v in form.items()
            if k not in reserved and v
        }
        self.schedules.append(
            {
                "project": project,
                "spider": spider,
                "args": args,
                "settings": settings,
            }
        )
        return httpx.Response(200, json={"status": "ok", "jobid": job_id})

    def _cancel(self, request: httpx.Request) -> httpx.Response:
        form = self._form(request)
        job = self._first(form, "job")
        was_running = any(j["id"] == job for j in self.running)
        self.running = [j for j in self.running if j["id"] != job]
        if job is not None:
            self.finished.append({"id": job})
        prevstate = "running" if was_running else None
        return httpx.Response(200, json={"status": "ok", "prevstate": prevstate})

    def _listjobs(self, request: httpx.Request) -> httpx.Response:
        if self.fail_listjobs:
            # Simulate scrapyd being unreachable (transport error).
            raise httpx.ConnectError("scrapyd unreachable", request=request)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "pending": self.pending,
                "running": self.running,
                "finished": self.finished,
            },
        )

    def _addversion(self, request: httpx.Request) -> httpx.Response:
        if self.fail_addversion:
            return httpx.Response(
                200, json={"status": "error", "message": "bad egg"}
            )
        return httpx.Response(
            200, json={"status": "ok", "spiders": self.spiders}
        )


class FakeRedisStreams:
    """In-memory Redis Streams double backed by ``fakeredis.aioredis``.

    Pass ``server=`` (a ``fakeredis.FakeServer``) to share one in-memory store
    across clients. Set ``fail_xadd`` / ``fail_streams`` to simulate Redis being
    unavailable for publishing (event-outbox replay tests).
    """

    def __init__(self, *, server: Any = None) -> None:
        kwargs: dict[str, Any] = {"decode_responses": False}
        if server is not None:
            kwargs["server"] = server
        self._c = fakeaioredis.FakeRedis(**kwargs)
        self.server = server
        self.fail_xadd = False
        self.fail_streams: set[str] = set()
        self.calls: list[tuple[str, Any]] = []

    async def xadd(
        self,
        stream: str,
        fields: dict[Any, Any],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> Any:
        self.calls.append(("xadd", stream))
        if self.fail_xadd or stream in self.fail_streams:
            raise RedisConnectionError("fake redis: xadd disabled")
        return await self._c.xadd(stream, fields, maxlen=maxlen, approximate=approximate)

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> Any:
        return await self._c.xreadgroup(group, consumer, streams, count=count, block=block)

    async def xack(self, stream: str, group: str, *ids: Any) -> int:
        return await self._c.xack(stream, group, *ids)

    async def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str = "0-0",
        *,
        count: int = 100,
    ) -> Any:
        return await self._c.xautoclaim(stream, group, consumer, min_idle_ms, start, count=count)

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._c.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:  # BUSYGROUP if it already exists
            if "BUSYGROUP" not in str(exc):
                raise

    async def xlen(self, stream: str) -> int:
        return await self._c.xlen(stream)

    async def aclose(self) -> None:
        await self._c.aclose()

    # --- test-only helpers -------------------------------------------------
    async def entries(self, stream: str) -> list[tuple[Any, dict[Any, Any]]]:
        return await self._c.xrange(stream)

    async def pending_count(self, stream: str, group: str) -> int:
        info = await self._c.xpending(stream, group)
        return int(info["pending"]) if info else 0


@pytest.fixture
def fake_server() -> Any:
    import fakeredis

    return fakeredis.FakeServer()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[Any]:
    """Factory building FakeRedisStreams instances, all closed on teardown."""
    created: list[FakeRedisStreams] = []

    def _make(*, server: Any = None) -> FakeRedisStreams:
        fr = FakeRedisStreams(server=server)
        created.append(fr)
        return fr

    yield _make
    for fr in created:
        await fr.aclose()


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "agent-data"
    d.mkdir()
    return d


def make_runner(workdir: Path, fake: FakeScrapyd) -> ScrapyRunner:
    client = ScrapydClient(
        base_url="http://scrapyd.test", transport=fake.transport()
    )
    store = StateStore(state_dir(workdir))
    return ScrapyRunner(client=client, store=store, logs_dir=scrapyd_logs_dir(workdir))


def write_log(workdir: Path, project: str, spider: str, job_id: str, body: str) -> Path:
    """Write a fake scrapyd job.log under the workdir and return its path."""
    path = scrapyd_logs_dir(workdir) / project / spider / f"{job_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def read_state(workdir: Path, execution_id: str) -> dict:
    path = state_dir(workdir) / f"{execution_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))
