"""Agent application factory and entrypoint.

``create_app()`` builds the FastAPI app: it constructs the agent runtime
(scrapyd client + Scrapy runner + state store, and optionally the scrapyd
subprocess manager) from settings and stores it on ``app.state.runtime`` so the
API works even under the test ASGI transport (which does NOT run the lifespan).
The lifespan only owns the scrapyd subprocess: it starts the child on enter and
stops/reaps it on exit. It also includes the root API router and registers a
global handler that renders ``AgentError`` as the frozen ``ErrorResponse``
envelope ``{code, message_key, detail}``.

``main()`` loads settings from ``DOPILOT_CONFIG`` and runs uvicorn with
``workers=1`` (single-instance hard constraint).
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from dopilot_protocol import ErrorResponse
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .api.router import api_router
from .config.loader import get_settings, load_settings
from .config.settings import Settings
from .deps import build_runtime
from .errors import AgentError


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``settings`` may be injected (tests / explicit run); otherwise they are
    resolved via the cached ``get_settings`` dependency. The runtime objects are
    built eagerly here (not only in the lifespan) so tests that drive the app
    over httpx ``ASGITransport`` still get a wired runtime on ``app.state``.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = app.state.runtime
        if runtime.process is not None:
            runtime.process.start()
        try:
            yield
        finally:
            if runtime.process is not None:
                runtime.process.stop()

    app = FastAPI(title="dopilot-agent", version=__version__, lifespan=lifespan)

    active = settings or get_settings()
    app.state.runtime = build_runtime(active)

    @app.exception_handler(AgentError)
    async def _agent_error_handler(_: Request, exc: AgentError) -> JSONResponse:
        envelope = ErrorResponse(
            code=exc.code, message_key=exc.message_key, detail=exc.detail
        )
        return JSONResponse(status_code=exc.status_code, content=envelope.model_dump())

    app.include_router(api_router)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="dopilot-agent")
    parser.add_argument("-b", "--bind", default=None, help="host to bind")
    parser.add_argument("-p", "--port", type=int, default=None, help="port to bind")
    args = parser.parse_args()

    settings = load_settings()
    host = args.bind or settings.agent.host
    port = args.port or settings.agent.port

    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
