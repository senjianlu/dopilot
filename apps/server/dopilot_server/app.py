"""Application factory + ``run()`` entrypoint.

``create_app`` mounts ``/api/v1``, serves the bundled Next static-export web UI
when present (one HTML file per route; no SPA always-index fallback),
enables CORS for the Next dev origin,
registers the global :class:`ApiError` -> error-envelope handler, attaches the
in-memory SSE :class:`SubscriptionManager`, and installs a lifespan that builds
the async engine/session factory plus the phase-1.5 Redis runtime (command
dispatcher + event/log consumers + heartbeat/event-stall reconcile loop, and the
slim egg-deploy HTTP client). The app NEVER creates tables (Alembic owns it).

Entrypoints:
- console script ``dopilot-server`` -> :func:`run`
- ``python -m dopilot_server.app`` -> :func:`run`
"""

from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .api.v1.router import router as api_v1_router
from .clients.agent import DEFAULT_TIMEOUT, AgentClient
from .config.loader import get_settings, load_settings
from .config.settings import Settings
from .db.engine import dispose_engines, get_session, get_sessionmaker
from .errors import ApiError
from .logs.sse import SubscriptionManager
from .redis.client import build_redis
from .redis.commands import CommandProducer
from .redis.consumers import EventConsumer, LogConsumer
from .redis.dispatcher import CommandDispatcher
from .redis.reconcile import RedisReconcileLoop
from .scheduler.runner import ScheduleRunner, build_schedule_runner

# Dev-only browser origins. Production is same-origin (the server hosts the
# exported static web assets), so CORS only matters when a developer runs the
# Next dev server (default :3000) against a separately running server.
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
DEFAULT_WEB_DIST = "/app/web"


def _error_envelope(error: ApiError) -> JSONResponse:
    """Render an :class:`ApiError` as the frozen ``{code,message_key,detail}``."""
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message_key": error.message_key,
            "detail": error.detail,
        },
    )


def _web_dist_path() -> Path | None:
    """Return the bundled SPA directory when it has a built ``index.html``."""
    configured = os.getenv("DOPILOT_WEB_DIST", DEFAULT_WEB_DIST)
    root = Path(configured).resolve()
    if (root / "index.html").is_file():
        return root
    return None


def _file_under(root: Path, path: str) -> Path | None:
    """Resolve a requested static path without allowing traversal outside root."""
    candidate = (root / path).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root):
        return None
    return candidate


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI app.

    ``settings`` may be injected (tests); otherwise the lifespan loads them via
    the cached ``get_settings`` dependency. The lifespan builds the async
    session factory and the Redis runtime (dispatcher + consumers + reconcile),
    and wires the session factory into the ``get_session`` dependency override.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = settings or get_settings()
        maker = get_sessionmaker(active.database.url)

        async def _session_dependency():
            async with maker() as session:
                yield session

        # Tests override get_session before the lifespan and use ASGITransport
        # (which does not run the lifespan at all). Only the real server path
        # gets here with no override -> build the Redis runtime (command
        # dispatcher + event/log consumers + reconcile loop) only in that case.
        owns_runtime = get_session not in app.dependency_overrides
        redis_client = None
        bg_engine = None
        egg_http: httpx.AsyncClient | None = None
        dispatcher: CommandDispatcher | None = None
        event_consumer: EventConsumer | None = None
        log_consumer: LogConsumer | None = None
        reconcile_loop: RedisReconcileLoop | None = None
        schedule_runner: ScheduleRunner | None = None
        if owns_runtime:
            app.dependency_overrides[get_session] = _session_dependency
            # Expose the request sessionmaker so endpoints that outlive a normal
            # request (the SSE stream) can open a SHORT-LIVED preflight session
            # and release the pooled connection before streaming.
            app.state.sessionmaker = maker
            # Background loops share ONE engine/pool, distinct from the request
            # pool, so long-lived SSE connections can never starve dispatch /
            # event-and-log consumption / reconcile.
            bg_engine = create_async_engine(
                active.database.url, pool_pre_ping=True, future=True
            )
            bg_maker = async_sessionmaker(bind=bg_engine, expire_on_commit=False)

            # Surviving server->agent HTTP path: egg deploy only.
            egg_http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
            app.state.agent_client = AgentClient(
                egg_http, active.agent_auth.shared_token
            )

            redis_client = build_redis(active.redis.url)
            producer = CommandProducer(redis_client, active.redis)
            dispatcher = CommandDispatcher(bg_maker, producer)
            event_consumer = EventConsumer(
                bg_maker, redis_client, consumer_name=active.redis.consumer_name
            )
            log_consumer = LogConsumer(
                bg_maker, redis_client, active, app.state.subscriptions,
                consumer_name=active.redis.consumer_name,
            )
            reconcile_loop = RedisReconcileLoop(bg_maker, active)

            dispatcher.start()
            event_consumer.start()
            log_consumer.start()
            reconcile_loop.start()
            app.state.command_dispatcher = dispatcher
            app.state.redis = redis_client

            # Phase 1.7: the single-instance schedule runner (OFF unless
            # [scheduler].enabled). Drives the schedules table via APScheduler.
            schedule_runner = build_schedule_runner(bg_maker, active, dispatcher)
            if schedule_runner is not None:
                await schedule_runner.start()
            app.state.schedule_runner = schedule_runner
        try:
            yield
        finally:
            if owns_runtime:
                if schedule_runner is not None:
                    await schedule_runner.stop()
                for worker in (
                    reconcile_loop, log_consumer, event_consumer, dispatcher
                ):
                    if worker is not None:
                        await worker.stop()
                if redis_client is not None:
                    await redis_client.aclose()
                if egg_http is not None:
                    await egg_http.aclose()
                if bg_engine is not None:
                    await bg_engine.dispose()
                app.dependency_overrides.pop(get_session, None)
                await dispose_engines()

    app = FastAPI(title="dopilot-server", lifespan=lifespan)
    # In-memory SSE fan-out lives on app.state so endpoints can reach it with or
    # without the lifespan having run (ASGITransport tests do not run lifespan).
    app.state.subscriptions = SubscriptionManager()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _error_envelope(exc)

    app.include_router(api_v1_router)
    web_dist = _web_dist_path()
    if web_dist is not None:
        not_found_page = web_dist / "404.html"

        def _resolve_web_file(path: str) -> Path | None:
            """Map a request path to an exported Next static file, or None.

            Next ``output: export`` with ``trailingSlash: true`` emits one HTML
            file per route at ``<route>/index.html`` (plus hashed assets under
            ``_next/``). Resolution order: a direct file first (assets, ``*.html``,
            ``index.txt``), then the ``<route>/index.html`` trailing-slash form,
            then a flat ``<route>.html`` for robustness. There is NO SPA
            always-``index.html`` fallback (that would mask real 404s).
            """
            asset = _file_under(web_dist, path)
            if asset is not None:
                return asset
            trimmed = path.strip("/")
            if trimmed:
                for candidate in (f"{trimmed}/index.html", f"{trimmed}.html"):
                    resolved = _file_under(web_dist, candidate)
                    if resolved is not None:
                        return resolved
            return None

        @app.get("/", include_in_schema=False)
        async def _serve_web_index() -> FileResponse:
            return FileResponse(web_dist / "index.html")

        @app.get("/{path:path}", include_in_schema=False)
        async def _serve_web_asset_or_route(path: str) -> FileResponse:
            # /api/* is API-only and must never resolve to a web asset.
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404)
            resolved = _resolve_web_file(path)
            if resolved is not None:
                return FileResponse(resolved)
            # Unknown non-API route -> exported 404 page (not an SPA always-200).
            if not_found_page.is_file():
                return FileResponse(not_found_page, status_code=404)
            raise HTTPException(status_code=404)

    return app


def run() -> None:
    """Console entrypoint: load config, parse bind/port, run uvicorn workers=1."""
    import uvicorn

    parser = argparse.ArgumentParser(prog="dopilot-server")
    parser.add_argument("-b", "--bind", default=None, help="bind host")
    parser.add_argument("-p", "--port", type=int, default=None, help="port")
    args = parser.parse_args()

    # load_settings reads DOPILOT_CONFIG itself when no path is passed.
    settings = load_settings()
    host = args.bind or settings.server.host
    port = args.port or settings.server.port

    # workers=1 is a hard single-instance constraint (in-process scheduler +
    # pull/SSE state are not shared across processes).
    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


if __name__ == "__main__":
    run()
