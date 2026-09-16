"""Scrapy runner: orchestrates run/stop/status over local scrapyd.

:class:`ScrapyRunner` is the agent's only phase-1 executor. It ties together
the :class:`~dopilot_agent.scrapyd.client.ScrapydClient`, the
:class:`~dopilot_agent.state.store.StateStore`, and job.log path resolution to
implement the ``/run`` / ``/stop`` / ``/status`` behavior the server pull-drives.

The state file is authoritative: status is resolved from the persisted
``scrapyd_job_id`` against scrapyd's ``listjobs``, so an agent restart with the
state file intact still resolves the correct status (no in-memory bookkeeping).
"""

from __future__ import annotations

from pathlib import Path

from dopilot_protocol import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentStopResponse,
    AttemptStatus,
)

from ..logcap import SETTING_NAME as LOG_CAP_SETTING
from ..scrapyd.client import ScrapydClient, ScrapydError
from ..state.store import AttemptState, StateStore


class RunnerError(Exception):
    """A run/deploy operation failed; carries a structured detail payload."""

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict = detail if detail is not None else {}


class ScrapyRunner:
    """Run/stop/status orchestration for Scrapy jobs via local scrapyd."""

    def __init__(
        self,
        *,
        client: ScrapydClient,
        store: StateStore,
        logs_dir: str | Path,
        max_job_log_bytes: int = 0,
    ) -> None:
        self._client = client
        self._store = store
        self._logs_dir = Path(logs_dir)
        # Log-flood guard: > 0 injects ``-s DOPILOT_JOB_LOG_CAP_BYTES`` into
        # every scheduled crawler (the in-process logcap hook enforces it);
        # 0 = disabled (nothing injected, matching the agent-wide "0 = off").
        self._max_job_log_bytes = max_job_log_bytes

    def log_path(self, project: str, spider: str, job_id: str) -> Path:
        """scrapyd writes job logs to logs_dir/{project}/{spider}/{job}.log."""
        return self._logs_dir / project / spider / f"{job_id}.log"

    async def schedule(self, req: AgentRunRequest) -> str:
        """Schedule a spider on local scrapyd and return its job id.

        No state is written here — the phase-1.5 command consumer manages the
        two-phase ``reserved`` -> ``started`` state file around this call. Raises
        :class:`RunnerError` on a scrapyd failure.
        """
        settings = dict(req.settings or {})
        if self._max_job_log_bytes > 0:
            settings[LOG_CAP_SETTING] = str(self._max_job_log_bytes)
        try:
            return await self._client.schedule(
                req.project,
                req.spider,
                version=req.version,
                settings=settings or None,
                args=req.args,
            )
        except ScrapydError as exc:
            raise RunnerError(
                f"failed to schedule spider: {exc.message}",
                detail={"project": req.project, "spider": req.spider, **exc.detail},
            ) from exc

    async def run(self, req: AgentRunRequest) -> AgentRunResponse:
        """Schedule a spider, persist execution state, return the remote job id."""
        job_id = await self.schedule(req)

        state = AttemptState(
            task_id=req.task_id,
            execution_id=req.execution_id,
            scrapyd_job_id=job_id,
            project=req.project,
            version=req.version,
            spider=req.spider,
            log_path=str(self.log_path(req.project, req.spider, job_id)),
        )
        self._store.write(state)

        return AgentRunResponse(
            task_id=req.task_id,
            execution_id=req.execution_id,
            remote_job_id=job_id,
            status=AttemptStatus.running,
        )

    async def stop(
        self, execution_id: str, task_id: str, *, signal: str | None = None
    ) -> AgentStopResponse:
        """Cancel an execution. Idempotent: stopping a gone job is not an error.

        ``signal`` is forwarded to scrapyd's ``cancel.json`` (the log-flood
        watchdog escalates from the default TERM to ``KILL``).
        """
        state = self._store.read(execution_id)
        if state is None:
            # No mapping: nothing we can cancel. Report unknown, not an error.
            return AgentStopResponse(
                task_id=task_id,
                execution_id=execution_id,
                status=AttemptStatus.unknown,
                stopped=False,
                detail={"reason": "no_state"},
            )

        try:
            body = await self._client.cancel(
                state.project, state.scrapyd_job_id, signal=signal
            )
        except ScrapydError as exc:
            # Job already gone/finished on scrapyd's side: resolve, don't error.
            status = await self._resolve_status(state)
            return AgentStopResponse(
                task_id=task_id,
                execution_id=execution_id,
                status=status,
                stopped=False,
                detail={"reason": "cancel_failed", "scrapyd": exc.detail},
            )

        prevstate = body.get("prevstate")
        # prevstate == "running"/"pending" means we actually stopped it; a null
        # prevstate means the job was already not running (idempotent no-op).
        if prevstate in ("running", "pending"):
            # Merge via re-read: ``state`` is stale after the await (the log
            # publisher may have flipped ``log_capped`` meanwhile).
            self._store.mark_canceled(execution_id)
            return AgentStopResponse(
                task_id=task_id,
                execution_id=execution_id,
                status=AttemptStatus.canceled,
                stopped=True,
                detail={"prevstate": prevstate},
            )

        status = await self._resolve_status(state)
        return AgentStopResponse(
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            stopped=False,
            detail={"prevstate": prevstate},
        )

    async def status(
        self, execution_id: str, task_id: str
    ) -> AgentStatusResponse:
        """Resolve an execution's current status from the state file + scrapyd."""
        state = self._store.read(execution_id)
        if state is None:
            # No state mapping at all: the server treats unknown as "lost".
            return AgentStatusResponse(
                task_id=task_id,
                execution_id=execution_id,
                remote_job_id=None,
                status=AttemptStatus.unknown,
                detail={"reason": "no_state"},
            )

        status = await self._resolve_status(state)
        return AgentStatusResponse(
            task_id=task_id,
            execution_id=execution_id,
            remote_job_id=state.scrapyd_job_id,
            status=status,
            exit_code=None,  # scrapyd 1.x does not expose exit codes.
        )

    async def is_job_alive(self, execution_id: str) -> bool | None:
        """Liveness ONLY, for stop confirmation. Never infers a terminal kind.

        ``True``  -- scrapyd still lists the job as running or pending.
        ``False`` -- listjobs SUCCEEDED and the job is in neither list, i.e. it
                     is confirmed not running any more.
        ``None``  -- scrapyd unreachable, so we cannot tell.

        Deliberately NOT :meth:`_resolve_status`: that one answers "what was the
        outcome", and returns ``unknown`` both when scrapyd is unreachable AND
        when listjobs succeeded but the job is in no list with no log on disk --
        exactly the shape a cancelled ``pending`` job leaves behind. Confirming
        a stop with it would wait out the whole deadline on a job that is
        demonstrably gone, then keep ``kill_pending`` set forever. It also
        sidesteps ``mark_canceled``: after a successful TERM ``_resolve_status``
        reports a departed job as ``canceled``, which is our own doing and must
        never be mistaken for an authoritative terminal.
        """
        state = self._store.read(execution_id)
        if state is None:
            return None
        try:
            jobs = await self._client.listjobs(state.project)
        except ScrapydError:
            return None
        job_id = state.scrapyd_job_id
        if self._in_list(jobs.get("running"), job_id):
            return True
        if self._in_list(jobs.get("pending"), job_id):
            return True
        return False

    async def _resolve_status(self, state: AttemptState) -> AttemptStatus:
        """Map scrapyd job lists onto an :class:`AttemptStatus`."""
        try:
            jobs = await self._client.listjobs(state.project)
        except ScrapydError:
            # scrapyd unreachable / unparseable: we CANNOT assert completion just
            # because a log file exists -- the job may still be running. Report
            # unknown so the server applies its lost/timeout policy instead of
            # falsely finalizing a running job as "finished". The log-exists
            # heuristic below is only safe when scrapyd is confirmed reachable
            # (listjobs returned).
            return AttemptStatus.unknown

        job_id = state.scrapyd_job_id
        if self._in_list(jobs.get("running"), job_id):
            return AttemptStatus.running
        if self._in_list(jobs.get("pending"), job_id):
            return AttemptStatus.running
        if self._in_list(jobs.get("finished"), job_id):
            return AttemptStatus.canceled if state.canceled else AttemptStatus.finished

        # listjobs SUCCEEDED (scrapyd reachable) but the job is in no list. If the
        # log exists the job ran and rotated out of the finished list (restart
        # recovery); otherwise scrapyd never knew this job id.
        if Path(state.log_path).exists():
            return AttemptStatus.canceled if state.canceled else AttemptStatus.finished
        return AttemptStatus.unknown

    @staticmethod
    def _in_list(jobs: object, job_id: str) -> bool:
        if not isinstance(jobs, list):
            return False
        return any(isinstance(j, dict) and j.get("id") == job_id for j in jobs)
