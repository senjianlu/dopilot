# Phase 2 — Claude progress

## 2026-06-20 — Feasibility review (read/analysis only)

- Task: validate Codex's phase-2 preflight conflict list + proposed direction.
  No application code edited.
- Output: `docs/phases/phase-2/00a-feasibility-review.md`.
- Outcome: 6/7 conflicts confirmed against current code; conflict 7 (README
  staleness) confirmed by inspection. Direction endorsed with one divergence —
  recommend keeping `script`/`docker` as wire capability keys and fixing
  `ARTIFACT_CAPABILITY` (seam translation) instead of canonicalizing
  `CapabilitySet`, which is the more disruptive option.
- Key files inspected: `packages/protocol/{common,streams,execution,logs}.py`,
  `services/{states,artifacts,templates,resolve,executions}.py`,
  `executors/{base,registry,scrapyd}.py`, `nodes/service.py`,
  `apps/agent/.../{config/settings,redis/commands,redis/logs,redis/heartbeat,runners/scrapyd,state/store}.py`,
  `apps/web/src/api/types.ts`, web build-artifacts/templates pages.
- Highest-risk change point identified: agent `redis/commands.py` runner-registry
  split + `state/store.py` `AttemptState` (scrapyd-shaped) — must keep Scrapy
  path unchanged.
- Open decisions raised for user: capability naming, wheel dependency/network
  policy, combined-vs-split log streams, launch contract + code-exec scope,
  interpreter/version, cancel grace, AttemptState evolution.

## 2026-06-20 — 2a/2b split plan review (read/analysis only)

- Task: validate the proposed phase-2 split (2a = id-name clean-cut, 2b =
  Python wheel shell-command runner). No application code edited.
- Output: `docs/phases/phase-2/00b-plan-review.md`.
- Verdict: split is sound — endorse. Two refinements: (1) 2a is a name-collision
  *swap* (`execution_id` changes meaning), so do it per-file compile-and-green,
  never a tree-wide `sed`; (2) 2a collapses the existing seam-translation
  boundary (wire/disk/DB names become the domain names), so it is a net
  simplification, and it requires NO public-API/web change.
- Key findings:
  - Collision traps where `execution_id` already correctly means `Execution.id`
    and must NOT be renamed: `api/v1/tasks.py:177,262`, `schemas.py` LogSnapshot/
    ExecutionView, `services/executions.py:225,342` (`get_execution`/
    `resolve_execution` public params), `logs/sse.py`, web `types.ts`/`tasks.ts`.
  - Seam rename surface: protocol (`streams.py`, legacy `agent.py`/`logs.py`),
    DB cols on `ExecutionLogFile`/`CommandOutbox`/`EventAudit` (new migration
    `0005`), server services + `redis/dispatcher.py`/`reconcile.py`/
    `logs/files.py`, agent `state/store.py` + `redis/*` + `runners/scrapyd.py`,
    on-disk paths (`{task_id}/{execution_id}.log`, `{execution_id}.json`,
    `{execution_id}.logpos`), and the full test suite as the regression net.
  - Compatibility: clean-cut safe, NO compat shim, but ONE hard precondition —
    quiesce (no in-flight executions) + flush Redis before upgrade; protocol+
    server+agent ship as one lockstep version.
  - 2b no-venv/shell design is coherent with the agent process/log/state seams
    (merged single `log` stream reuses the chain unchanged; process-group
    SIGTERM->10s->SIGKILL; per-run state keyed by the post-2a atomic
    `execution_id`). Flagged install-pollution + `--target` alternative, shell/
    pipefail exit-code authority, and concurrent-install lock as gaps.
- Remaining decisions surfaced: legacy-type rename scope, 2a cutover
  precondition, wheel install isolation, dep/network policy, shell exit-code
  semantics, cancel-grace knob, AttemptState additive evolution, capability
  naming (carried from 00a), combined-vs-split streams.
