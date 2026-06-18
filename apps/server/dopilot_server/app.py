"""Application factory + ``run()`` entrypoint.

``create_app`` mounts ``/api/v1``, enables CORS for the Vite dev origins,
registers the global :class:`ApiError` -> error-envelope handler, and installs
a lifespan that builds the async engine/session factory from settings. The app
NEVER creates tables (Alembic owns the schema).

Entrypoints:
- console script ``dopilot-server`` -> :func:`run`
- ``python -m dopilot_server.app`` -> :func:`run`
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.v1.router import router as api_v1_router
from .config.loader import get_settings, load_settings
from .config.settings import Settings
from .db.engine import dispose_engines, get_session, get_sessionmaker
from .errors import ApiError

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
    session factory and wires it into the ``get_session`` dependency override.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = settings or get_settings()
        maker = get_sessionmaker(active.database.url)

        async def _session_dependency():
            async with maker() as session:
                yield session

        # Wire the real session factory in. Tests instead override
        # get_session before entering the lifespan, so only install ours when
        # the dependency has not already been overridden.
        if get_session not in app.dependency_overrides:
            app.dependency_overrides[get_session] = _session_dependency
        try:
            yield
        finally:
            # Do not dispose engines that tests own; only dispose when we built
            # the app's own session factory here.
            if app.dependency_overrides.get(get_session) is _session_dependency:
                app.dependency_overrides.pop(get_session, None)
                await dispose_engines()

    app = FastAPI(title="dopilot-server", lifespan=lifespan)

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
