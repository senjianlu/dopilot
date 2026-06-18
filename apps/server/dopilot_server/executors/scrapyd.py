"""Scrapy-via-scrapyd executor (phase-1 implementation; phase-0 stub)."""

from __future__ import annotations

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse

from ..errors import ApiError
from .base import BaseExecutor


class ScrapydExecutor(BaseExecutor):
    """Dispatches Scrapy jobs to scrapyd. Real logic lands in phase 1."""

    task_type = "scrapy"

    async def run(self, request: ExecutionRunRequest) -> ExecutionRunResponse:
        raise ApiError(
            501,
            "execution.not_implemented",
            "errors.notImplemented",
            {"phase": 1},
        )
