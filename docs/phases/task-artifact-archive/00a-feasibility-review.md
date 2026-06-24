# 00a — Feasibility Review: Build Artifact Archive State

Reviewer: Claude (implementation/test agent). Scope: validate the brief
(`00-brief.md`) against the current code. No implementation performed.

## Verdict

**Feasible as written, with two must-fix design points and a few decisions to
confirm.** The brief aligns well with the existing seams: the archive concept is
a nullable timestamp + derived boolean, the create/update vs. run distinction
maps onto code that already exists, and re-upload dedup already avoids touching
unrelated columns. The main real work is one backend validation seam and one Web
edit-form edge case; both are tractable.

## Blocking issues

1. **`_require_artifact` is shared by both the binding path and the run path.**
   `services/templates.py:78` `_require_artifact()` (runnable-only) is called by
   `create_template`, `update_template`, **and** `build_run_request`
   (`templates.py:234`). If the archive check is added inside it, it will also
   block runs and schedule dispatch — directly violating brief §"Do not re-check
   archive state during template run or schedule dispatch." Implementation MUST
   add a *separate* bindable check (runnable **and** unarchived) used only by
   create/update, and leave `build_run_request` on the runnable-only path. This
   is exactly the distinction the brief calls for (§Required Behavior), so it is
   a design constraint, not a blocker on intent — but it is a correctness trap if
   missed.

2. **Web edit form: the archived current binding disappears from the picker.**
   `app/(app)/templates/page.tsx:127-129` builds `runnableArtifacts =
   artifacts.filter(a => a.runnable)` and the `<Select>` only renders
   `SelectItem`s from that list (`:383`). A shadcn `Select` renders the trigger
   label only when a matching `SelectItem` for the current value exists. Once the
   picker also excludes archived artifacts, a template bound to an archived
   artifact will render an **empty/placeholder** trigger, and saving could
   silently rebind or fail validation. The brief explicitly requires this case
   not break and to "show the current binding clearly." Implementation must
   special-case the currently-bound archived artifact (e.g. render it as a
   present-but-disabled item, or a read-only display) without adding it to the
   selectable set. This is the highest-risk UI item.

## Risky assumptions

- **`archived` belongs only on `BuildArtifactView`, not on the task snapshot.**
  `services/artifacts.py:217 artifact_snapshot()` is the immutable run descriptor
  frozen onto `Task.template_snapshot` and also feeds `BuildArtifactOption`
  (task-list filter, from frozen snapshots). Archive state is mutable and live;
  it must **not** be written into the snapshot. The brief only asks for it on the
  view/upload responses — keep it there. Flag so the implementer doesn't add it
  to `artifact_snapshot`/`BuildArtifactOption`.

- **Re-upload safety is already structurally true.** `upsert_scrapy`
  (`artifacts.py:70`) and `upsert_wheel` (`:119`) refresh display metadata but
  never reference `archived_at`; as long as the implementation does not add a
  reset, identical-bytes re-upload preserves archive state for free. The risk is
  only a careless edit, not a missing mechanism.

- **Migrations are not exercised by pytest.** `tests/conftest.py:382` builds the
  schema via `Base.metadata.create_all`, so adding `archived_at` to the model
  auto-covers the test DB, but migration `0012` (head is `0011`) is validated
  **only** by `alembic upgrade head` against PostgreSQL. The migration must be
  hand-verified; a broken migration will pass pytest. Note the sandbox has no
  Postgres/sudo (see repo memory) — `alembic upgrade head` likely cannot run
  locally and should be reported as an environment blocker, not a code failure.

- **`runnable` already includes `python_wheel`** (`states.py:63`
  `RUNNABLE_ARTIFACT_TYPES = {scrapy, python_wheel}`), matching brief line 28.
  The brief's "must not be overloaded to mean selectable" is satisfied by the new
  bindable check; no change to `runnable` semantics needed.

## Missing decisions / questions for Codex

1. **`archived_at` timestamp source/format:** server-side `func.now()` vs.
   `datetime.now(timezone.utc)` in service code, serialized via existing `_iso`.
   Recommend app-side aware UTC for symmetry with action endpoints. Confirm.
2. **Artifact list ordering/visual:** does an archived artifact stay in
   created-at order with a badge, or sort to the bottom? Brief says "remain
   visible"; assuming in-place + badge unless told otherwise.
3. **Task-list filter options:** confirm archived state should **not** affect the
   `BuildArtifactOption` filter on the tasks page (those derive from frozen task
   snapshots, not live artifacts). Assumed out of scope.
4. **Archive of a non-runnable (reserved) type:** `docker_image` etc. are not
   runnable and not template-bindable today. Should archive/unarchive be allowed
   on any artifact regardless of runnable, or only runnable ones? Recommend
   allow on any artifact (archive is orthogonal to runnable). Confirm.
5. **Idempotent response on no-op:** archiving an already-archived artifact —
   return 200 with current view and keep the original `archived_at` (don't
   refresh the timestamp)? Recommend yes (stable timestamp). Confirm.

## Suggested scope / sequencing changes

- Sequence backend before web: (1) model + migration `0012`; (2) view/schema
  fields; (3) the bindable-vs-runnable seam in `services/templates.py` + action
  endpoints in `api/v1/artifacts.py`; (4) backend tests; (5) Web types/api,
  picker exclusion + edit-form current-binding handling, i18n `归档`/`取消归档`;
  (6) web tests. This lets the contract settle before the SPA consumes it.
- Add explicit backend tests for the trap in Blocking issue #1: an archived
  artifact still runs via `POST /templates/{id}/run` and schedule dispatch, while
  create/rebind to it is rejected. This is the behavior most likely to regress.
- Add a web test asserting the edit form for a template bound to an archived
  artifact renders the current binding and does not offer it as a fresh
  selectable option.
- Keep `artifact_snapshot`/`BuildArtifactOption` untouched (see risky
  assumptions) — call this out in the implementation prompt to prevent scope
  creep into the frozen-snapshot path.

## Verification feasibility

- `pytest apps/server/tests/`, `ruff check apps packages`,
  `corepack pnpm --filter web test` — expected runnable locally.
- `alembic upgrade head` — needs a live PostgreSQL; likely **blocked** in the
  sandbox. Report the exact blocker per brief §Required Verification rather than
  skipping silently.
