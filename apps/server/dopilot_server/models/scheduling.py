"""Execution-template and schedule models (phase 1.8 clean-cut).

The scheduling domain that sits *above* a :class:`Task`:

- :class:`ExecutionTemplate` — a reusable run definition bound to exactly one
  :class:`BuildArtifact` (``build_artifact_id``). When a task is created from a
  template (template run, schedule trigger-now, or a schedule timer firing), the
  RESOLVED run is COPIED into an immutable ``Task.template_snapshot`` at creation
  time; later edits to the template never mutate historical tasks (brief
  acceptance: snapshot immutability). The core-domain ``artifact_type`` is
  DERIVED from the bound build artifact — templates no longer carry a
  ``task_type``.
- :class:`Schedule` — a timer definition that references one execution template
  and creates tasks from its resolved snapshot. Phase 1.7 supports an
  ``interval`` trigger (seconds) and a simple ``cron`` expression. Phase 1.8
  adds an ``overrides`` JSONB payload (execution params / node strategy /
  node ids — never the build artifact).

JSON columns use ``JSONB`` on PostgreSQL and fall back to ``JSON`` on SQLite
(tests), mirroring :class:`dopilot_server.models.execution.Task`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


def _new_id() -> str:
    return uuid.uuid4().hex


class ExecutionTemplate(Base):
    """A reusable run definition bound to one build artifact (phase 1.8)."""

    __tablename__ = "execution_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 1.8: mandatory binding to one build artifact. Nullable in the DB so a
    # legacy template whose artifact descriptor could not be resolved during
    # migration stays READABLE; application validation requires it for every
    # new/updated template. The runnable discriminator (artifact_type) is derived
    # from this artifact — templates no longer carry a ``task_type``.
    build_artifact_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("build_artifacts.id"), nullable=True, index=True
    )
    # Scrapy-specific run defaults. ``project`` / ``version`` are resolved from
    # the bound build artifact (NOT user-editable); they are kept here as the
    # snapshot default and for legacy data. ``spider`` is the user's choice.
    project: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    spider: Mapped[str | None] = mapped_column(String, nullable=True)
    settings: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    args: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    node_strategy: Mapped[str] = mapped_column(
        String, nullable=False, default="all"
    )
    node_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Schedule(Base):
    """A timer referencing one execution template (interval or cron).

    ``trigger_type`` is ``interval`` (uses ``interval_seconds``) or ``cron``
    (uses the ``cron`` 5-field crontab expression). Pause/resume is out of scope
    — there is no paused state. ``overrides`` (phase 1.8) is a bounded JSONB
    payload merged over the template defaults at firing time (precedence:
    schedule override > execution template default > build artifact default); it
    may carry ``settings`` / ``args`` / ``spider`` / ``node_strategy`` /
    ``node_ids`` but NEVER ``build_artifact_id``.
    """

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_template_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("execution_templates.id"),
        nullable=False,
        index=True,
    )
    # interval | cron
    trigger_type: Mapped[str] = mapped_column(
        String, nullable=False, default="interval"
    )
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 5-field crontab expression (minute hour day month day_of_week).
    cron: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 1.8: bounded override payload (never build_artifact_id).
    overrides: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
