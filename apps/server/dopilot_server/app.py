"""Application factory + ``run()`` entrypoint.

``create_app`` mounts ``/api/v1``, enables CORS for the Vite dev origins,
registers the global :class:`ApiError` -> error-envelope handler, attaches the
in-memory SSE :class:`SubscriptionManager`, and installs a lifespan that builds
the async engine/session factory, the agent HTTP client, and the background log
reconcile loop. The app NEVER creates tables (Alembic owns the schema).

Entrypoints:
- console script ``dopilot-server`` -> :func:`run`
- ``python -m dopilot_server.app`` -> :func:`run`
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .api.v1.router import router as api_v1_router
from .clients.agent import DEFAULT_TIMEOUT, AgentClient
from .config.loader import get_settings, load_settings
from .config.settings import Settings
from .db.engine import dispose_engines, get_session, get_sessionmaker
from .errors import ApiError
from .logs.loop import ReconcileLoop
from .logs.sse import SubscriptionManager

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI app.

    ``settings`` may be injected (tests); otherwise the lifespan loads them via
    the cached ``get_settings`` dependency. The lifespan builds the async
    session factory, the agent HTTP client, and the reconcile loop, and wires
    the session factory into the ``get_session`` dependency override.
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
        # gets here with no override -> build the prod wiring (agent client +
        # reconcile loop) only in that case.
        owns_runtime = get_session not in app.dependency_overrides
        loop: ReconcileLoop | None = None
        http: httpx.AsyncClient | None = None
        loop_engine = None
        if owns_runtime:
            app.dependency_overrides[get_session] = _session_dependency
            # Expose the request sessionmaker so endpoints that outlive a normal
            # request (the SSE stream) can open a SHORT-LIVED preflight session
            # and release the pooled connection before streaming.
            app.state.sessionmaker = maker
            http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
            agent_client = AgentClient(http, active.agent_auth.shared_token)
            app.state.agent_client = agent_client
            app.state.agent_http = http
            # The reconcile loop runs on its OWN engine/pool so that long-lived
            # SSE connections pinning request-pool connections can never starve
            # log draining / status polling.
            loop_engine = create_async_engine(
                active.database.url, pool_pre_ping=True, future=True
            )
            loop_maker = async_sessionmaker(
                bind=loop_engine, expire_on_commit=False
            )
            loop = ReconcileLoop(
                loop_maker, active, agent_client, app.state.subscriptions
            )
            loop.start()
            app.state.reconcile_loop = loop
        try:
            yield
        finally:
            if owns_runtime:
                if loop is not None:
                    await loop.stop()
                if loop_engine is not None:
                    await loop_engine.dispose()
                if http is not None:
                    await http.aclose()
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
