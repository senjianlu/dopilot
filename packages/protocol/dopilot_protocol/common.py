"""Shared common schemas: capabilities and the universal error envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CapabilitySet(BaseModel):
    """Declares which scheduled-object types an agent/node can execute."""

    scrapy: bool = False
    script: bool = False
    docker: bool = False


class ErrorResponse(BaseModel):
    """Universal error envelope shape: {code, message_key, detail}."""

    code: str
    message_key: str
    detail: dict[str, Any] = Field(default_factory=dict)
