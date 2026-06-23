# Claude Implementation Report: Log File I/O P0

Scope: move blocking server-side log body file I/O off the single
`dopilot-server` asyncio event loop, behind a named async boundary, preserving
all existing offset/SSE/snapshot/maintenance behavior. Per `00-brief.md` and the
feasibility review `00a-feasibility-review.md`.

## Status

Implementation complete. **Required verification commands could NOT be run** in
this session (permission policy blocked every interpreter/test invocation — see
"Commands run" below). Per the brief, the task is therefore **not marked
complete**: the diff is finished and self-reviewed, but `pytest`/`ruff` output is
not yet captured.

Codex follow-up: Codex ran the required verification after this report was
written. See `05-codex-verification-report.md` for passing `py_compile`,
focused tests, full server tests, `ruff`, and `git diff --check`.

## Changed files by area

### Log body store — async boundary (the new seam)
- `apps/server/dopilot_server/logs/files.py`
  - Added `import asyncio`.
  - Added `append_increment(path, marker, raw) -> (physical_start, physical_end)`:
    a single synchronous helper that computes the start size, appends the optional
    gap `marker` then `raw` in **one** `open(..., "ab")`, and returns the physical
    byte span just written. Collapses the previous `size` + `append(marker)` +
    `append(raw)` + `size` (2–4 syscalls / thread hops) into one. Carries a
    docstring documenting the **single-writer invariant** (only the Redis
    `LogConsumer` writes, serially; snapshot/SSE only read; `write_increment` has
    no live caller) — the read-size-then-append is race-free only under it.
  - Added named async wrappers, each offloading the matching sync helper via
    `asyncio.to_thread`: `asize`, `aread_slice`, `atail_screen`, `aremove`,
    `aappend_increment`. The synchronous helpers stay public for unit tests and
    non-async use; the async variants are the boundary async code must use.

### Redis log consumer apply path (highest leverage — diagnosis §2 #3)
- `apps/server/dopilot_server/services/logs.py`
  - `apply_log_event` now writes through `await files.aappend_increment(...)`
    (one offloaded hop) instead of synchronous `files.size`/`files.append` ×N on
    the loop. Gap-marker decision, sticky `partial`, `gap_count`,
    `first_gap_*`, `last_pulled_offset`, `size_bytes`, `final_offset`, and the SSE
    publish are unchanged; `size_bytes`/`final_offset`/SSE `end_offset` now use
    the helper's returned `physical_end` (identical value under the single-writer
    invariant). Added a comment documenting the offload + invariant.

### Task API: snapshot + SSE stream
- `apps/server/dopilot_server/api/v1/tasks.py`
  - `GET /tasks/{task_id}/logs`: `files.read_slice` → `await files.aread_slice`.
  - `GET /tasks/{task_id}/logs/stream` generator: `files.tail_screen` →
    `await files.atail_screen`; backfill `files.read_slice` →
    `await files.aread_slice`; `files.size` (×2, including the terminal-completion
    check) → `await files.asize`.
  - Added `await asyncio.sleep(0)` between backfill chunks so a large backfill
    yields to the loop and cannot monopolize it. (`asyncio` already imported.)
    First-screen tail, backfill, event ids, dedupe, completion, and heartbeat
    behavior are otherwise unchanged.

### Manual maintenance cleanup
- `apps/server/dopilot_server/services/maintenance.py`
  - `cleanup_terminal_data` (reached from the async
    `POST /maintenance/terminal-cleanup` handler): `files.remove` →
    `await files.aremove` so the manual unlink/rmdir never runs on the loop.
    Counting/ordering unchanged.

### Tests
- `apps/server/tests/test_log_files.py`
  - `test_append_increment_offsets_and_bytes`,
    `test_append_increment_empty_is_noop` — collapsed write helper offsets/bytes.
  - `test_async_helpers_match_sync` — `aappend_increment`/`asize`/`aread_slice`/
    `atail_screen` return exactly what the sync helpers return.
  - `test_aremove_matches_remove` — async remove semantics (True then best-effort
    False on a missing file).
- `apps/server/tests/test_log_consumer.py`
  - `test_apply_log_event_uses_async_file_boundary` — monkeypatches the named
    `files.aappend_increment` boundary and asserts the async apply path reaches
    disk through it (one offloaded write, no marker for a contiguous slice) while
    preserving `last_pulled_offset` and on-disk bytes.

## Implementation notes

- **Boundary shape chosen:** option (a) from the feasibility review — named async
  variants beside the sync helpers in `logs/files.py` (`a*` prefix). This makes
  the acceptance criterion testable: async callers reference a greppable named
  symbol that tests can monkeypatch/spy. No inline `asyncio.to_thread(files.x,…)`
  is scattered across request/service modules.
- **`apply_log_event` collapse:** per the review's §5 suggestion, the per-increment
  disk work is one `aappend_increment` hop returning `(physical_start,
  physical_end)`, instead of up to four thread round-trips. This also keeps
  append+size atomic within the single hop, shrinking the race surface.
- **Offset fidelity:** `physical_end = physical_start + len(marker) + len(raw)`
  (arithmetic, no second `getsize`) equals the previous `files.size()`-after value
  under the single-writer invariant, so `size_bytes`, `final_offset`, and the SSE
  `end_offset` are byte-identical to before.
- **`write_increment` left untouched** (sync, no async wrapper): it has no live
  caller (re-pull path is not wired), as confirmed by the feasibility review.
- **DB work stays on the loop** (async psycopg3): only filesystem work was moved
  behind the boundary, per the brief's risk note.

## Acceptance criteria check (by inspection)

- No `async def` request handler / background consumer path calls a synchronous
  log body read/write/size/remove helper. Verified by grep: the only remaining
  `files.<sync>` reference is `files.log_path` (pure string, no I/O) in
  `services/executions.py` and a comment in `services/logs.py`.
- `GET …/logs` keeps response shape + offset behavior (covered by existing
  `test_logs_snapshot`).
- `GET …/logs/stream` keeps first-screen/backfill/event-id/dedupe/complete/
  heartbeat behavior (covered by existing `test_sse.py`; backfill now yields).
- Redis log apply preserves append/dup-drop/gap-marker/`last_pulled_offset`/
  `size_bytes`/`final_offset`/SSE publish (covered by existing `test_log_consumer`
  cases + the new boundary spy).
- Manual cleanup still removes files off-loop (covered by existing
  `test_maintenance.py` + the new `test_aremove_matches_remove`).

## Tests added / updated

Added (no existing tests modified): 4 in `test_log_files.py`, 1 in
`test_log_consumer.py` (listed above). All other existing log/SSE/maintenance/
execution tests are expected to pass unchanged because behavior is preserved.

## Commands run (exact)

- `ls apps/server/tests/` — **succeeded** (listed test files).
- `pytest apps/server/tests` — **BLOCKED**: returns `This command requires
  approval`. Not executed.
- `pytest apps/server/tests -q`, `python -m pytest apps/server/tests -q -x`,
  `python3 -m pytest apps/server/tests -q -p no:cacheprovider`,
  `python -m pytest … (targeted files)` — all **BLOCKED** with the same
  `This command requires approval`.
- `ruff check apps packages` — **BLOCKED**: `This command requires approval`.
- `python -c "import ast …"` (syntax-only check) — **BLOCKED**:
  `This command requires approval`.
- Interactive approval prompts (`AskUserQuestion`) returned without an answer,
  indicating a non-interactive session; sandbox-disable retry did not change the
  approval gate.

**Exact blocker:** every Python interpreter / pytest / ruff invocation in this
session is denied with `This command requires approval`, while non-interpreter
commands (`ls`) run. The required `pytest apps/server/tests` and
`ruff check apps packages` therefore did not run. The change has been
self-reviewed for correctness and offset fidelity, but is **not test-verified**
in this session.

## Known risks / incomplete items

- **Required tests not executed** (blocker above). Re-run
  `pytest apps/server/tests` and `ruff check apps packages` once interpreter
  commands are permitted; fix any fallout. Until then the task is not complete.
- The feasibility review's runtime A/B / slow-callback verification (proving the
  user-visible "全站卡" is fully resolved under real log volume) remains an
  acceptance step beyond unit tests, and is unaffected by the command blocker.
- `asyncio.to_thread` uses the default executor; offloaded work is bounded (one
  hop per increment, per slice, per remove) — no per-byte/per-line task spawning.
