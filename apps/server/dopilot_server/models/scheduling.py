"""Task-template and schedule models (phase 1.7 packet 2).

The scheduling domain that sits *above* a :class:`Task`:

- :class:`TaskTemplate` — a reusable run definition. When a task is created from
  a template (manual run-from-template, schedule trigger-now, or a schedule
  timer firing), the template's payload is COPIED into an immutable
  ``Task.template_snapshot`` at creation time; later edits to the template never
  mutate historical tasks (brief acceptance: snapshot immutability).
- :class:`Schedule` — a timer definition that references one template and
  creates tasks from its snapshot. Phase 1.7 supports an ``interval`` trigger
  (seconds) and a simple ``cron`` expression; pause/resume is out of scope, so
  there is no paused column.

``task_type`` is forward-compatible (script/docker arrive later) but only
``"scrapy"`` is valid in phase 1.7.

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


class TaskTemplate(Base):
    """A reusable Scrapy run definition, copied into each task snapshot."""

    __tablename__ = "task_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Forward-compatible; only "scrapy" is validated in phase 1.7.
    task_type: Mapped[str] = mapped_column(
        String, nullable=False, default="scrapy"
    )
    project: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    spider: Mapped[str | None] = mapped_column(String, nullable=True)
    # Optional artifact descriptor (hash/filename/fetch_path) copied into the run.
    artifact: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
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
    """A timer that references one template and creates tasks from its snapshot.

    ``trigger_type`` is ``interval`` (uses ``interval_seconds``) or ``cron``
    (uses the ``cron`` 5-field crontab expression). Pause/resume is out of scope
    for phase 1.7 — there is no paused state.
    """

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("task_templates.id"), nullable=False, index=True
    )
    # interval | cron
    trigger_type: Mapped[str] = mapped_column(
        String, nullable=False, default="interval"
    )
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 5-field crontab expression (minute hour day month day_of_week).
    cron: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
