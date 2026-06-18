"""SQLAlchemy declarative base.

The app NEVER calls ``Base.metadata.create_all()`` — Alembic is the only
schema authority (see ``migrations/``). The test suite is the sole exception
and documents that fact in ``tests/conftest.py``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
