"""Executor registry: maps ``artifact_type`` -> executor instance (phase 1.8).

``"scrapy"`` (phase 1.8) and ``"python_wheel"`` (phase 2b) are runnable.
``"docker_image"`` arrives in a later phase; it registers here without changing
dispatch code.
"""

from __future__ import annotations

from ..errors import ApiError
from .base import BaseExecutor
from .python_wheel import PythonWheelExecutor
from .scrapyd import ScrapydExecutor

EXECUTOR_REGISTRY: dict[str, BaseExecutor] = {
    "scrapy": ScrapydExecutor(),
    "python_wheel": PythonWheelExecutor(),
    # "docker_image": DockerExecutor(),        # later phase
}


def get_executor(artifact_type: str) -> BaseExecutor:
    """Return the executor for ``artifact_type`` or raise a 400 ``ApiError``."""
    executor = EXECUTOR_REGISTRY.get(artifact_type)
    if executor is None:
        raise ApiError(
            400,
            "execution.unknown_artifact_type",
            "errors.unknownArtifactType",
            {"artifact_type": artifact_type},
        )
    return executor
