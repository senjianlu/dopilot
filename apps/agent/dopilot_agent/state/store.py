"""Atomic per-attempt JSON state store.

:class:`AttemptState` is the persisted mapping for one execution attempt.
:class:`StateStore` reads/writes/deletes/lists those files under
``{workdir}/state/executions``.

Durability rules:
- writes go to a temp file in the same directory then ``os.replace`` onto the
  final path, so a crash never leaves a half-written ``{attempt_id}.json``;
- reads of a missing OR corrupt/half-written file return ``None`` (never raise
  to the caller), so a torn file behaves exactly like "no state".
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class AttemptState(BaseModel):
    """Persisted state for one execution attempt.

    ``scrapyd_job_id`` is the job id local scrapyd assigned; ``log_path`` is the
    absolute path scrapyd writes the job log to. ``canceled`` records that a
    stop succeeded so ``/status`` can report ``canceled`` rather than
    ``finished`` for a job that left the running list after a cancel.
    """

    execution_id: str
    attempt_id: str
    scrapyd_job_id: str
    project: str
    version: str | None = None
    spider: str
    log_path: str
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)
    canceled: bool = False


class StateStore:
    """File-backed store of :class:`AttemptState` under a state directory."""

    def __init__(self, base_dir: str | os.PathLike[str]) -> None:
        # {workdir}/state/executions
        self._dir = Path(base_dir)

    @property
    def dir(self) -> Path:
        return self._dir

    def path_for(self, attempt_id: str) -> Path:
        return self._dir / f"{attempt_id}.json"

    def write(self, state: AttemptState) -> AttemptState:
        """Atomically persist ``state`` (refreshing ``updated_at``)."""
        state.updated_at = _utcnow_iso()
        self._dir.mkdir(parents=True, exist_ok=True)
        final = self.path_for(state.attempt_id)
        tmp = final.with_suffix(f".{os.getpid()}.tmp")
        payload = json.dumps(state.model_dump(), ensure_ascii=False)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        return state

    def read(self, attempt_id: str) -> AttemptState | None:
        """Return the persisted state, or ``None`` if missing/corrupt."""
        path = self.path_for(attempt_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Half-written / corrupt file: treat as missing, do not raise.
            return None
        try:
            return AttemptState.model_validate(data)
        except Exception:
            return None

    def delete(self, attempt_id: str) -> bool:
        """Remove the state file. Returns ``True`` if a file was deleted."""
        path = self.path_for(attempt_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def list_attempt_ids(self) -> list[str]:
        """Return attempt ids that currently have a state file on disk."""
        if not self._dir.is_dir():
            return []
        ids: list[str] = []
        for entry in self._dir.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                ids.append(entry.stem)
        return sorted(ids)
