# 00a · Phase 1.7 feasibility review (Claude)

Scope: implementation feasibility of `docs/phases/phase-1.7/00-brief.md` against
the current code. No code was changed. Citations are `path:line`.

## 1. Verdict

**Feasible with changes.**

The domain split (template → task → execution, schedule → template) maps cleanly
onto the existing code, and most acceptance criteria (all/random/selected →
N atomic units, immutable snapshot, rollup) are *already* satisfied by the
current `Execution`/`ExecutionAttempt` mechanics — only relabeled. There are no
hard technical blockers, but four design points must be locked by Codex before
implementation, and one instruction in the brief (step 4) should be reversed
because it actively manufactures the "half-renamed" hazard Codex is worried
about.

The single most important change: **do not rename the Redis/disk/agent
identifiers.** Keep `execution_id` (= parent, becomes *task*) and `attempt_id`
(= atomic, becomes *execution*) exactly as they are on the wire and on disk, and
rename only the server DB/service/API/web vocabulary. This resolves three of
Codex's five concerns at once (wire-field meaning, log-path migration, and the
half-renamed `execution_id` trap) and leaves the agent completely untouched.

## 2. Blocking issues

None are technically unsolvable, but these two must be **decided** before a brief
is finalized, because they change the schema/migration shape:

- **B1 — Reverse brief step 4 ("`execution_id` … must refer to the atomic
  execution").** The wire already carries *two* ids: `AgentCommand` /
  `AgentEvent` / `AgentLogEvent` all have both `execution_id` and `attempt_id`
  (`packages/protocol/dopilot_protocol/streams.py:91-99,182-192,215-223`). The
  atomic unit on the wire is **`attempt_id`**, not `execution_id` — it is the
  agent's idempotency key, its state-file name (`{attempt_id}.json`,
  `apps/agent/dopilot_agent/state/store.py:73-74`), its local mutex/CAS key, and
  the `command_outbox`/`event_audit` join key. Redefining `execution_id` to mean
  "atomic" would force the parent id to be renamed too **and** invert the agent's
  entire idempotency vocabulary for zero functional gain. Decision required:
  adopt a **documented wire↔domain naming seam** — wire/disk/agent stay
  `(execution_id=task, attempt_id=execution)`; server DB/API/web use
  `(task_id, execution_id)`; the event/log consumers translate at the boundary.
  If Codex instead insists the wire be renamed, that pulls the entire agent into
  this phase and roughly doubles the blast radius (`apps/agent/**`, all agent
  tests) — that should be an explicit, separately-scoped decision, not implied by
  step 4.

- **B2 — Physical table rename vs. logical wrap, and whether existing data must
  survive.** Tables today are `executions` (parent) and `execution_attempts`
  (atomic) (`apps/server/dopilot_server/models/execution.py:33,66`). Two options:
  (a) **physical rename** `executions→tasks`, `execution_attempts→executions`,
  with consistent column renames (parent refs `execution_id→task_id`, atomic refs
  `attempt_id→execution_id`) in one `0004` migration — clean end state, no
  lingering inversion; (b) **logical wrap** — keep table/column names, only rename
  the Python classes (`Execution`→`Task` with `__tablename__="executions"`,
  `ExecutionAttempt`→`Execution` with `__tablename__="execution_attempts"`) —
  near-zero migration risk but leaves a *permanent* physical inversion (table
  `executions` holds tasks), which is exactly the half-renamed state the brief's
  Risks section warns against. Recommend **(a)** because this is greenfield
  (single admin, no production deployment), so "preserve existing data where
  feasible" (brief step 1) is low-stakes — confirm dev data may be dropped, then
  do a clean rename. This decision cannot be deferred; it dictates `0004`.

## 3. Risky assumptions

- **R1 — "preserving existing data where feasible" understates the inversion
  cost.** A data-preserving inversion of two cross-referenced tables plus
  `execution_log_files` (PK `(execution_id, attempt_id, stream)`,
  `models/execution.py:125-130`), `command_outbox`, and `event_audit` is
  fiddly. Assuming preservation is *not* required (greenfield) removes the risk;
  if it *is* required, this is a meaningfully larger migration. Tie to B2.

- **R2 — log-path migration is only needed if you rename wire/disk ids.** The
  body path is `{root}/YYYY/MM/{execution_id}/{attempt_id}.log`
  (`apps/server/dopilot_server/logs/files.py:3-4,24-41`). If wire/disk ids stay
  stable (B1), **no log migration happens** — bytes on disk and the
  `execution_log_files` PK are physically unchanged; only their conceptual labels
  move. The brief's "log path/index migration" concern evaporates under B1. It
  becomes real *only* if you take the rename to the wire, which is the thing to
  avoid.

- **R3 — coalesce conflicts with decision #2 only if mis-keyed.** Decision #2
  ("concurrent repeated runs allowed; do not coalesce/reject") and
  `refactor/00 §任务投递` ("定时任务必须做 coalesce 抑制") are *both* satisfiable
  because they target different things: #2 forbids blocking a new run because a
  prior run is still **running**; refactor/00 requires suppressing **undispatched
  same-schedule backlog** during a Redis outage. The current primitive
  `has_unterminated_for_target` is keyed on the human label `Execution.target`
  (`apps/server/dopilot_server/services/outbox.py:141-166`), which would wrongly
  suppress legitimate concurrent runs. It is currently **dormant** (docstring:
  "The scheduler (phase 2) calls this") — no live caller — so there is no
  regression to fix, but phase 1.7 introduces the scheduler and therefore must
  define the policy now (see §4 Q3).

- **R4 — most "node strategy → execution count" work already exists.** The
  per-node loop in `ScrapydExecutor.run`
  (`apps/server/dopilot_server/executors/scrapyd.py:65-76`) already creates one
  attempt + one run-outbox + one log file per selected node via
  `select_target_nodes` / `reduce_nodes` (`nodes/service.py:211-240`). The
  all/random/selected acceptance criteria are largely a relabel, not new logic.
  The only behavioral change is the zero-node case (R5). Low risk — do not
  re-architect this.

- **R5 — zero-node path inverts the current control flow.** Today
  `select_target_nodes` raises a 409 **before** any row is created
  (`scrapyd.py:46-52`; `nodes/service.py:228-239`) precisely to avoid a
  half-baked run. The brief wants the opposite: create the task, then on empty
  selection persist it with zero executions + a visible no-target state. This is
  feasible but needs: a new **terminal** task status `no_target` (not in
  `states.py` today — `EXEC_*` at `services/states.py:19-28`); a creation-time
  short-circuit that sets it directly (rollup over an empty set returns `None`,
  `states.py:145-148`, so a zero-execution task must NOT go through rollup or it
  stays queued forever); and `is_valid_execution_transition` / reconcile must
  leave it alone (reconcile already joins on active executions+attempts,
  `reconcile.py:125-138`, so a childless task is naturally skipped — but the task
  status itself must be in `EXEC_TERMINAL`). See Q2 for where the "reason" lives.

- **R6 — public API/web surface inverts.** `ExecutionView`/`AttemptView`
  (`apps/web/src/api/types.ts:144-170`) become `TaskView`/`ExecutionView`;
  `execution_view`/`execution_summary`/`attempt_view`
  (`services/executions.py:234-282`) and `/api/v1/executions` invert their nesting
  (task → `executions[]`). SSE/log endpoints key on the parent id today
  (`logs/sse.py`, stream-token), which becomes `task_id`; under B1 the route
  params can keep their physical ids and just relabel. Mechanical but broad; see
  §5 for the compat-adapter scope cut.

## 4. Missing decisions / questions for Codex

- **Q1 (ties B1): Accept the wire↔domain naming seam?** Recommended: yes — wire,
  disk, and agent keep `(execution_id, attempt_id)`; server domain uses
  `(task_id, execution_id)`; consumers translate and the seam is documented in
  `streams.py` and `files.py`. Confirm, or explicitly fund the full agent rename.

- **Q2: Where does a no-target task's reason live?** There is no task-level event
  store today (`event_audit` is Redis-dedupe only,
  `models/event_audit.py`). Brief item 3 forbids a fake execution. Recommended:
  a `status_reason` (+ optional `status_detail` JSON) column on the task row —
  no new events table. Confirm the column shape, and the enum value
  (`no_target`).

- **Q3: Coalesce policy for the new scheduler.** Recommended: key coalesce on
  `schedule_id`, suppress a timer firing only when that schedule still has an
  **undispatched** task (queued execution OR pending/dispatching outbox, per
  `refactor/00 §任务投递`); never suppress because a prior run is merely running;
  never coalesce manual or trigger-now runs. This honors both decision #2 and
  refactor/00. Rewrite `has_unterminated_for_target` from `target`-keyed to
  schedule-keyed (`outbox.py:141-166`). Confirm.

- **Q4: Scheduler runtime.** CLAUDE.md pins APScheduler 3.10.x and the
  single-instance / `workers=1` constraint is already in force. Confirm
  APScheduler (interval + cron) is the intended trigger engine for phase 1.7, and
  that trigger-now simply invokes the same snapshot→dispatch path synchronously
  (no second code path). Pause/resume is already out of scope.

- **Q5: `task_type` is fixed to `scrapy` this phase** — confirm templates/tasks
  still carry the column (forward-compat for script/docker) even though only
  `scrapy` is validated.

## 5. Suggested scope cuts / sequencing changes

- **Cut the dual-naming compatibility adapters for the public API** (brief step 2
  / "preserve wire compatibility where practical"). There are no external API
  consumers (single admin, greenfield, web is in-repo). Maintaining
  `/api/v1/executions` *and* `/api/v1/tasks` with two vocabularies is the surest
  way to land in the half-renamed state the brief warns about. Do a clean cutover
  of `/api/v1` + web in this phase. Keep compatibility **only** at the immutable
  seam that genuinely must not move: the Redis/disk/agent wire (B1).

- **Reorder so the rename precedes the new features.** Recommended sequence:
  1. `0004` migration + ORM/class rename + `states.py` (`no_target`, terminal
     set, transitions) + service/API/web relabel — land this *green* first
     (pure rename, behavior-preserving except the new status existing unused).
  2. Zero-node task path (invert select-then-create; R5).
  3. Templates + snapshot copy (immutability test is cheap).
  4. Schedules + trigger-now + scheduler runner + coalesce policy (Q3/Q4).
  5. Web template/schedule pages last.
  Doing the rename as an isolated, test-green step is what keeps the inversion
  from leaking into the feature work.

- **Do not touch the agent.** Under B1 the agent's command/event/log/state code
  (`apps/agent/**`) needs no change. Keep it out of the brief's file list so it is
  not "helpfully" renamed.

- **Reframe brief step 4** from "make `execution_id` mean atomic" to "the wire
  keeps `execution_id`=task / `attempt_id`=execution; the server translates at the
  consumer boundary and documents the seam." This is the single highest-leverage
  edit to the brief.

## 6. Net

No blockers that stop work; the architecture fits. Lock B1 (wire stable + naming
seam) and B2 (clean physical rename, drop dev data), answer Q2–Q3 (no-target
reason column + schedule-keyed coalesce), and sequence the rename as a standalone
green step. With those, every acceptance criterion in the brief is reachable, and
most of the all/random/selected/rollup behavior is already implemented and only
needs relabeling.
