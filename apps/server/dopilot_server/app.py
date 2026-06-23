"""Application factory + ``run()`` entrypoint.

``create_app`` mounts ``/api/v1``, serves the bundled Next static-export web UI
when present (one HTML file per route; no SPA always-index fallback),
enables CORS for the Next dev origin,
registers the global :class:`ApiError` -> error-envelope handler, attaches the
in-memory SSE :class:`SubscriptionManager`, and installs a lifespan that builds
the async engine/session factory plus the phase-1.5 Redis runtime (command
dispatcher + event/log consumers + heartbeat/event-stall reconcile loop). The
server reaches agents only over Redis + agent-initiated heartbeats; there is no
server -> agent HTTP path (phase 2.2.7). The app NEVER creates tables (Alembic
owns it).

Entrypoints:
- console script ``dopilot-server`` -> :func:`run`
- ``python -m dopilot_server.app`` -> :func:`run`
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .agent_token import ensure_runtime_agent_token
from .api.v1.router import router as api_v1_router
from .config.loader import DEFAULT_CONFIG_PATH, get_settings, load_settings
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

    ``settings`` may be injected (tests + the ``run()`` runtime); otherwise the
    lifespan loads them via the cached ``get_settings`` dependency. The lifespan
    builds the async session factory and the Redis runtime (dispatcher +
    consumers + reconcile), and wires the session factory into the
    ``get_session`` dependency override.

    When ``settings`` is injected, it is ALSO wired into the ``get_settings``
    dependency (phase 2.2.4). Without this, FastAPI dependencies that call
    ``Depends(get_settings)`` (e.g. heartbeat auth) would read the cached loader
    settings — which lacks the runtime-generated agent token — instead of the
    mutated runtime object, leaving heartbeat auth off. Tests set their own
    ``get_settings`` override after ``create_app`` (it wins over this one).
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
                if bg_engine is not None:
                    await bg_engine.dispose()
                app.dependency_overrides.pop(get_session, None)
                await dispose_engines()

    app = FastAPI(title="dopilot-server", lifespan=lifespan)
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
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


logger = logging.getLogger("dopilot_server")


def _agent_token_cli(argv: list[str]) -> int:
    """``dopilot-server agent-token print [--quiet]`` (phase 2.2.4).

    Loads settings with the SAME default config path as :func:`run`, then reads
    or generates the persisted server<->agent token. It does NOT require the DB,
    Redis, the ASGI app, or uvicorn, so it is safe to invoke via
    ``docker exec <server> dopilot-server agent-token print`` to retrieve the
    token an operator needs to join an agent.
    """
    parser = argparse.ArgumentParser(prog="dopilot-server agent-token")
    sub = parser.add_subparsers(dest="action", required=True)
    print_parser = sub.add_parser(
        "print", help="print the active server<->agent token"
    )
    print_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print only the bare token (no env-var prefix or hints)",
    )
    args = parser.parse_args(argv)

    settings = load_settings(default_path=DEFAULT_CONFIG_PATH)
    result = ensure_runtime_agent_token(settings)

    if args.quiet:
        print(result.token)
        return 0

    print(f"DOPILOT_AGENT_TOKEN={result.token}")
    if result.source == "configured":
        print("# source: configured ([agents].agent_token / DOPILOT_AGENT_TOKEN)")
    elif result.source == "disk":
        print(f"# source: persisted generated token ({result.path})")
    else:
        print(f"# source: newly generated and persisted ({result.path})")
    print(
        "# Set this DOPILOT_AGENT_TOKEN on every agent so it can join this "
        "server. Token auth is NOT transport encryption."
    )
    return 0


def _serve() -> None:
    """Resolve the runtime token, then run uvicorn workers=1."""
    import uvicorn

    parser = argparse.ArgumentParser(prog="dopilot-server")
    parser.add_argument("-b", "--bind", default=None, help="bind host")
    parser.add_argument("-p", "--port", type=int, default=None, help="port")
    args = parser.parse_args()

    # load_settings reads DOPILOT_CONFIG itself when no path is passed, then
    # falls back to the baked server default so the image needs no DOPILOT_CONFIG.
    settings = load_settings(default_path=DEFAULT_CONFIG_PATH)

    # Phase 2.2.4: resolve the single server<->agent token at the runtime
    # boundary (load_settings stays pure). A configured token wins; otherwise a
    # token is read-or-generated under server.data_dir and applied to
    # settings.agents.agent_token BEFORE create_app, so inbound heartbeat auth
    # (Depends(get_settings), wired by create_app) sees the same value the agent
    # presents (the agent uses it for heartbeat + artifact/wheel fetch).
    token_result = ensure_runtime_agent_token(settings)
    if token_result.is_generated_path:
        # Log a concise join hint once, only for the persisted generated-token
        # path. Never log the admin API token.
        logger.warning(
            "server<->agent machine auth ON using the persisted generated token "
            "(%s, source=%s). Retrieve it with `dopilot-server agent-token "
            "print` and set DOPILOT_AGENT_TOKEN on every agent.",
            token_result.path,
            token_result.source,
        )

    host = args.bind or settings.server.host
    port = args.port or settings.server.port

    # workers=1 is a hard single-instance constraint (in-process scheduler +
    # pull/SSE state are not shared across processes).
    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


def run() -> None:
    """Console entrypoint.

    ``dopilot-server -b <host> -p <port>`` runs the server (the normal command).
    ``dopilot-server agent-token print [--quiet]`` is the operator subcommand to
    read/generate the persisted server<->agent token without booting the app.
    """
    argv = sys.argv[1:]
    if argv and argv[0] == "agent-token":
        raise SystemExit(_agent_token_cli(argv[1:]))
    _serve()


if __name__ == "__main__":
    run()
