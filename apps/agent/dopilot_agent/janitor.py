"""Agent-local disk janitor (resource caps, C1/C4).

A single always-on background loop that bounds agent disk growth with a TTL
fallback and an LRU cache cap — the counterpart to the server's retention sweep.
It implements the TTL fallback GC that the architecture already documented
("agent 另有 TTL 兜底 GC") but which was never built:

- **Workspace/log/state GC (C1)** — a TERMINAL execution's Python-wheel workspace
  (``{workdir}/python_wheel/workspaces/{id}``), its ``.logpos`` cursor and its
  state file are removed once older than ``completed_log_ttl_days``. An ORPHAN
  workspace (no readable state, no live process, quiet on disk) is removed once
  older than ``orphan_log_ttl_days``. A running execution's files are NEVER
  removed — three independent guards must all agree it is safe (not in the
  runner's in-memory active set, its ``job.pgid`` process is not alive, and the
  workspace tree has been quiet for the full TTL).

- **Artifact/wheel cache LRU eviction (C4)** — when the combined
  ``{workdir}/artifacts`` cache exceeds ``artifact_cache_max_bytes`` the
  least-recently-used sha entries are evicted (LRU key = the ``.ready`` marker
  mtime, touched on every cache hit). An entry referenced by a running execution,
  or with an install/deploy lock held, is never evicted.

The loop runs once at startup and then every ``janitor_interval_seconds``. Every
step is guarded so one failure never skips the rest, and the loop never dies.
Blocking filesystem work is offloaded to a thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .config.settings import Settings
from .disk_status import DiskStatus
from .runners.python_wheel import PGID_SIDECAR, PythonWheelRunner
from .state.store import StateStore

logger = logging.getLogger(__name__)


def _pgid_alive(pgid: int) -> bool:
    """True if the process group exists (resource caps, C1 liveness guard).

    ``PermissionError`` means the group exists but is owned by another user — we
    treat that as ALIVE (conservative: never delete a workspace we cannot prove
    is dead). Only ``ProcessLookupError`` proves it is gone.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _newest_mtime(root: Path) -> float:
    """Newest mtime anywhere under ``root`` (a live job writing job.log keeps this
    fresh, so it is a second liveness guard)."""
    try:
        newest = root.stat().st_mtime
    except OSError:
        return 0.0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                m = os.stat(os.path.join(dirpath, name)).st_mtime
            except OSError:
                continue
            newest = max(newest, m)
    return newest


def _tree_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


class AgentJanitor:
    """Periodic local-disk janitor (single-instance background loop)."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: StateStore,
        wheel_runner: PythonWheelRunner,
        cursor_dir: str | os.PathLike[str],
        artifacts_root: str | os.PathLike[str],
        release: Callable[[str], None] | None = None,
        active_ids: Callable[[], set[str]] | None = None,
        lock_for: Callable[[str], object] | None = None,
        disk_status: DiskStatus | None = None,
        interval_seconds: float | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._runner = wheel_runner
        self._cursor_dir = Path(cursor_dir)
        self._artifacts_root = Path(artifacts_root)
        # Resource dashboard (D1): where each sweep publishes its disk sample.
        self._disk_status = disk_status
        # Called after an execution's files are removed, so the consumer can drop
        # its in-memory bookkeeping (locks, EOF dedup, runner dicts).
        self._release = release
        # Resource caps (R-04): the FULL active set (runner in-proc ∪ the command
        # consumer's in-flight ids) and the same per-execution lock the consumer
        # uses, so a workspace is never deleted while its command is mid-flight.
        # Falls back to the runner-only set when no consumer is wired.
        self._active_ids = active_ids or wheel_runner.active_execution_ids
        self._lock_for = lock_for
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else float(settings.agent.janitor_interval_seconds)
        )
        self._wheel_workspace_root = (
            Path(settings.agent.workdir) / "python_wheel" / "workspaces"
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # --- one sweep ---------------------------------------------------------
    async def sweep_once(self, *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        try:
            await self._sweep_workspaces(now)
        except Exception:  # noqa: BLE001 - never abort the sweep
            logger.error("janitor: workspace sweep failed", exc_info=True)
        try:
            await asyncio.to_thread(self._sweep_cache)
        except Exception:  # noqa: BLE001
            logger.error("janitor: cache sweep failed", exc_info=True)
        # Resource dashboard (D1): publish a fresh disk sample for the heartbeat.
        # All FS work runs in a thread; a per-item failure only nulls that item.
        if self._disk_status is not None:
            try:
                sample = await asyncio.to_thread(self._collect_disk_sample)
                self._disk_status.update(sample)
            except Exception:  # noqa: BLE001 - never abort the sweep
                logger.error("janitor: disk sample failed", exc_info=True)

    # --- C1: workspace / log / state TTL GC --------------------------------
    async def _sweep_workspaces(self, now: float) -> None:
        """Two-phase to close the mid-flight race (R-04): scan filesystem
        candidates in a thread against a snapshot of the active set, then commit
        each deletion on the event loop UNDER the per-execution lock, re-checking
        the *fresh* active set + age so a command that started spawning between
        scan and delete is never clobbered."""
        root = self._wheel_workspace_root
        if not root.is_dir():
            return
        snapshot = self._active_ids()
        candidates = await asyncio.to_thread(
            self._scan_candidates, now, snapshot
        )
        for execution_id, path in candidates:
            await self._commit_removal(execution_id, path, now)

    def _scan_candidates(
        self, now: float, active: set[str]
    ) -> list[tuple[str, Path]]:
        out: list[tuple[str, Path]] = []
        for entry in self._wheel_workspace_root.iterdir():
            if entry.is_dir() and self._is_removable(entry, entry.name, now, active):
                out.append((entry.name, entry))
        return out

    async def _commit_removal(
        self, execution_id: str, path: Path, now: float
    ) -> None:
        lock_cm = (
            self._lock_for(execution_id)
            if self._lock_for is not None
            else contextlib.nullcontext()
        )
        async with lock_cm:
            # Re-check the FRESH active set on the event loop (a command may have
            # started processing since the scan), then re-verify fs age/pgid.
            fresh = self._active_ids()
            still = await asyncio.to_thread(
                self._is_removable, path, execution_id, now, fresh
            )
            if not still:
                return
            await asyncio.to_thread(self._remove_files, execution_id, path)
        # Release in-memory bookkeeping AFTER dropping the lock.
        if self._release is not None:
            try:
                self._release(execution_id)
            except Exception:  # noqa: BLE001 - release must not break the sweep
                logger.warning(
                    "janitor: release callback failed for %s", execution_id,
                    exc_info=True,
                )
        logger.info("janitor: removed execution %s (%s)", execution_id, path)

    def _is_removable(
        self, workspace: Path, execution_id: str, now: float, active: set[str]
    ) -> bool:
        """All three guards must agree (resource caps, C1)."""
        if execution_id in active:
            return False  # guard 1: active set (runner in-proc ∪ consumer in-flight)
        pgid = self._read_pgid(workspace)
        if pgid is not None and _pgid_alive(pgid):
            return False  # guard 2: pgid process still alive
        state = self._store.read(execution_id)
        terminal = state is not None and state.phase == "done"
        ttl = (
            self._settings.agent.completed_log_ttl_days * 86400
            if terminal
            else self._settings.agent.orphan_log_ttl_days * 86400
        )
        return (now - _newest_mtime(workspace)) >= ttl  # guard 3: quiet period

    def _read_pgid(self, workspace: Path) -> int | None:
        try:
            return int(
                (workspace / PGID_SIDECAR).read_text(encoding="utf-8").strip()
            )
        except (OSError, ValueError):
            return None

    def _remove_files(self, execution_id: str, workspace: Path) -> None:
        """Delete the on-disk workspace, state file and .logpos cursor (thread)."""
        shutil.rmtree(workspace, ignore_errors=True)
        self._store.delete(execution_id)
        cursor = self._cursor_dir / f"{execution_id}.logpos"
        try:
            cursor.unlink(missing_ok=True)
        except OSError:
            pass

    # --- C4: artifact/wheel cache LRU eviction -----------------------------
    def _sweep_cache(self) -> None:
        entries = self._cache_entries()
        total = sum(e["size"] for e in entries)
        cap = self._settings.agent.artifact_cache_max_bytes
        if cap <= 0 or total <= cap:
            return
        referenced = self._referenced_wheel_shas()
        # LRU: evict oldest-ready-first. Referenced entries are never evicted; each
        # remaining candidate is evicted only while HOLDING its cache lock (R-03),
        # so it can never race a concurrent fetch/install/reuse.
        evictable = [e for e in entries if e["sha"] not in referenced]
        evictable.sort(key=lambda e: e["mtime"])
        for entry in evictable:
            if total <= cap:
                break
            if self._evict_locked(entry, referenced):
                total -= entry["size"]
                logger.info(
                    "janitor: evicted cache entry %s (%s, %d bytes)",
                    entry["sha"], entry["kind"], entry["size"],
                )

    def _evict_locked(self, entry: dict, referenced: set[str]) -> bool:
        """Evict a cache entry only while holding its ``.lock`` (R-03).

        Acquires the SAME ``O_CREAT|O_EXCL`` lock the cache uses for
        fetch/install/reuse; if the lock is already held (an install/reuse is in
        flight) the entry is skipped this sweep. Under the lock the reference set
        is re-checked, then the body + ready marker are removed and the lock is
        released. This makes eviction mutually exclusive with the cache."""
        lock_path: Path = entry["lock"]
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False  # install/reuse in flight — leave it
        except OSError:
            return False
        try:
            # Re-check under the lock: a just-started run may reference it now.
            if entry["sha"] in self._referenced_wheel_shas():
                return False
            return self._evict(entry)
        finally:
            os.close(fd)
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _cache_entries(self) -> list[dict]:
        entries: list[dict] = []
        scrapy_dir = self._artifacts_root / "scrapy"
        if scrapy_dir.is_dir():
            for egg in scrapy_dir.glob("*.egg"):
                sha = egg.stem
                ready = scrapy_dir / f"{sha}.egg.ready"
                lock = scrapy_dir / f"{sha}.egg.lock"
                entries.append({
                    "kind": "scrapy",
                    "sha": sha,
                    "size": _safe_size(egg),
                    "mtime": _safe_mtime(ready if ready.exists() else egg),
                    "lock": lock,
                    "paths": [egg, ready],
                })
        wheel_dir = self._artifacts_root / "python_wheel"
        if wheel_dir.is_dir():
            for sha_dir in wheel_dir.iterdir():
                if not sha_dir.is_dir():
                    continue
                sha = sha_dir.name
                ready = sha_dir / ".ready"
                lock = sha_dir / ".lock"
                entries.append({
                    "kind": "python_wheel",
                    "sha": sha,
                    "size": _tree_size(sha_dir),
                    "mtime": _safe_mtime(ready if ready.exists() else sha_dir),
                    "lock": lock,
                    "paths": [sha_dir],
                })
        return entries

    def _referenced_wheel_shas(self) -> set[str]:
        """Shas installed for a currently non-terminal execution (never evict).

        A running wheel job has its install ``site`` dir on PYTHONPATH; evicting it
        mid-run would break the job. The sha is the parent dir name of the state's
        ``install_path`` (``{root}/python_wheel/{sha}/site``). Scrapy cache eggs
        are not needed at runtime (scrapyd keeps its own deployed copy), so they
        are not protected here.
        """
        referenced: set[str] = set(self._runner.active_execution_ids())
        shas: set[str] = set()
        for execution_id in self._store.list_execution_ids():
            state = self._store.read(execution_id)
            if state is None:
                continue
            running = state.phase != "done" or execution_id in referenced
            if running and state.install_path:
                shas.add(Path(state.install_path).parent.name)
        return shas

    @staticmethod
    def _evict(entry: dict) -> bool:
        ok = False
        for path in entry["paths"]:
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    ok = True
                else:
                    path.unlink(missing_ok=True)
                    ok = True
            except OSError:
                continue
        return ok

    # --- D1: disk-usage sample (published to the heartbeat) ----------------
    def _collect_disk_sample(self) -> dict:
        """Assemble a fixed-shape disk sample (counts/bytes only, no file lists).

        Runs in a worker thread. Each sub-item is guarded independently: a
        failure (e.g. an unreadable dir) nulls only that item and never aborts
        the sweep. ``sampled_at`` + ``interval_seconds`` let the server judge
        staleness (2x the interval). Every byte/count uses the STRICT sample
        helpers (``_dir_bytes`` / ``_count_*``) so an access failure nulls the
        sub-item instead of masking as 0 — including the cache metric, which is
        measured directly (NOT reused from the tolerant eviction ``_tree_size``)
        and therefore reflects the real, post-eviction tree."""
        s = self._settings
        workdir = Path(s.agent.workdir)
        sample: dict = {
            "sampled_at": datetime.now(UTC).isoformat(),
            "interval_seconds": s.agent.janitor_interval_seconds,
        }
        sample["workspaces"] = _guard(
            lambda: {
                "count": _count_dirs(self._wheel_workspace_root),
                "bytes": _dir_bytes(self._wheel_workspace_root),
            }
        )
        sample["cache"] = _guard(
            lambda: {
                "bytes": _dir_bytes(self._artifacts_root),
                "limit": s.agent.artifact_cache_max_bytes,
            }
        )
        sample["scrapyd"] = _guard(
            lambda: {"bytes": _dir_bytes(workdir / "scrapyd")}
        )
        outbox_dir = s.redis.event_outbox_dir
        if outbox_dir:
            sample["outbox"] = _guard(
                lambda: {
                    "files": _count_glob(Path(outbox_dir), "*.json"),
                    "bytes": _dir_bytes(Path(outbox_dir)),
                    "limit": s.redis.event_outbox_max_files,
                }
            )
        sample["state"] = _guard(
            lambda: {
                "executions": len(self._store.list_execution_ids()),
                "logpos": _count_glob(self._cursor_dir, "*.logpos"),
            }
        )
        sample["volume"] = _guard(lambda: _volume(workdir))
        return sample

    # --- loop --------------------------------------------------------------
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.sweep_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("janitor tick failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _guard(fn: Callable[[], dict]) -> dict | None:
    """Run a sample sub-collector; None if it raises (item-level isolation)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - a bad sub-item nulls only itself
        return None


# Disk-sample size/count helpers. Unlike the cache-eviction ``_tree_size`` (which
# tolerates errors so eviction never stalls), these DISTINGUISH a genuinely-absent
# directory from an ACCESS FAILURE: ONLY ``FileNotFoundError`` means "not created
# yet" (-> 0); ``PermissionError`` and any other ``OSError`` PROPAGATE so ``_guard``
# nulls that sub-item. A misconfigured/unreadable dir must never be reported as a
# fake zero (resource dashboard D1, review R-01). They avoid ``Path.exists()`` and
# ``Path.glob()``, both of which swallow permission errors into a false "absent".


def _raise(exc: OSError) -> None:
    raise exc


def _dir_bytes(root: Path) -> int:
    """Byte size under ``root``. Absent dir -> 0; an access failure propagates.
    A file vanishing mid-walk is benign and skipped."""
    total = 0
    try:
        walker = os.walk(root, onerror=_raise)
        for dirpath, _dirs, files in walker:
            for name in files:
                try:
                    total += os.stat(os.path.join(dirpath, name)).st_size
                except FileNotFoundError:
                    continue  # vanished mid-walk — benign
    except FileNotFoundError:
        return 0  # top dir not created yet — legit empty
    return total


def _count_dirs(root: Path) -> int:
    """Count subdirectories of ``root``. Absent -> 0; access failure propagates.

    Only a vanished entry (``FileNotFoundError``) is skipped; a ``PermissionError``
    from ``entry.is_dir()`` propagates so ``_guard`` nulls the sub-item rather than
    returning a too-small "normal" count (review R-01)."""
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return 0
    count = 0
    for entry in entries:
        try:
            if entry.is_dir():
                count += 1
        except FileNotFoundError:
            continue  # entry vanished mid-scan — benign
    return count


def _count_glob(root: Path, pattern: str) -> int:
    """Count ``root`` entries matching ``pattern``. Absent -> 0; access failure
    propagates. Uses ``os.scandir`` (not ``Path.glob``, which swallows scan
    errors into a false 0)."""
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return 0
    return sum(1 for entry in entries if fnmatch.fnmatch(entry.name, pattern))


def _volume(path: Path) -> dict:
    usage = shutil.disk_usage(path)
    return {"total": usage.total, "used": usage.used, "free": usage.free}
