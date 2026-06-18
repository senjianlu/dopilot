"""Executor registry: maps ``task_type`` -> executor instance.

Only ``"scrapy"`` is registered in phase 0. ``"script"`` arrives in phase 2 and
``"docker"`` in phase 3; both register here without changing dispatch code.
"""

from __future__ import annotations

from ..errors import ApiError
from .base import BaseExecutor
from .scrapyd import ScrapydExecutor

EXECUTOR_REGISTRY: dict[str, BaseExecutor] = {
    "scrapy": ScrapydExecutor(),
    # "script": ScriptExecutor(),   # phase 2
    # "docker": DockerExecutor(),   # phase 3
}


def get_executor(task_type: str) -> BaseExecutor:
    """Return the executor for ``task_type`` or raise a 400 ``ApiError``."""
    executor = EXECUTOR_REGISTRY.get(task_type)
    if executor is None:
        raise ApiError(
            400,
            "execution.unknown_task_type",
            "errors.unknownTaskType",
            {"task_type": task_type},
        )
    return executor
