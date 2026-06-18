"""Scheduler package skeleton (no timers in phase 0).

Phase 1 backs this with APScheduler ``>=3.10,<4`` (importlib-based; we never
use 3.6.0, which imports the removed ``pkg_resources``). It will run a SINGLE
in-process ``BackgroundScheduler`` with NO distributed lock — which is exactly
why the server is single-replica and uvicorn runs ``workers=1`` (multiple
workers/replicas would fire every timer multiple times). This is a hard
constraint, not a temporary limitation.

``build_scheduler`` below is a stub: it constructs nothing that runs and is
NOT started anywhere in phase 0.
"""

from __future__ import annotations


def build_scheduler():  # pragma: no cover - phase-1 stub, intentionally inert
    """Placeholder factory. Returns None; no scheduler is created or started.

    Wiring (job stores, executors, timezone from
    ``SchedulerSettings``) lands in phase 1.
    """
    return None
