"""Agent application factory and entrypoint.

``create_app()`` builds the FastAPI app: includes the root API router and
registers a global handler that renders ``AgentError`` as the frozen
``ErrorResponse`` envelope ``{code, message_key, detail}``.

``main()`` loads settings from ``DOPILOT_CONFIG`` and runs uvicorn with
``workers=1`` (single-instance hard constraint).
"""

from __future__ import annotations

import argparse

import uvicorn
from dopilot_protocol import ErrorResponse
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .api.router import api_router
from .config.loader import load_settings
from .errors import AgentError


def create_app() -> FastAPI:
    app = FastAPI(title="dopilot-agent", version=__version__)

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

    uvicorn.run(create_app(), host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
