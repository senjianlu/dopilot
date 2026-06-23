# Feasibility Review: Log File I/O P0

Reviewer: Claude Code. Scope: implementation feasibility of `00-brief.md` against
HEAD (`master`, `8df5445`). No code was changed.

## 1. Verdict

**Feasible** — no blocking issues. The change is mechanical: `logs/files.py` is a
pure leaf module and every on-loop synchronous caller is enumerable and matches
the brief. The architecture constraints (single-worker, Redis→file→PG→SSE) are
untouched.

Caller inventory confirmed (the brief's list is complete and correct):

- `api/v1/tasks.py`: `read_slice` (:218 snapshot, :350 backfill), `tail_screen`
  (:335), `size` (:348, :362).
- `services/logs.py` `apply_log_event`: `size` (:70, :88), `append` (:83, :86).
- `services/maintenance.py` `cleanup_terminal_data`: `remove` (:150), reached
  from the async `POST /maintenance/terminal-cleanup` handler.
- No others: `services/executions.py` uses only `files.log_path` (pure string,
  no I/O); `write_increment` has **no live caller** (re-pull path is not wired).

## 2. Blocking issues

None.

## 3. Risky assumptions

- **Root-cause is assumed, not proven.** `asyncio.to_thread` helps because
  CPython releases the GIL during the `read`/`write`/`open` syscalls, so other
  coroutines progress. But `read_slice`/`tail_screen` also `.decode(...)` up to
  ~1MB, which holds the GIL — it runs off the loop thread but still contends.
  Net win is real; "fully fixes 全站卡" is not guaranteed. Keep the diagnosis
  §7 A/B + slow-callback verification as an acceptance step, not just unit tests.
- **`apply_log_event` correctness depends on the single-writer invariant.** After
  offloading, that function gains `await` points between `size` → `append marker`
  → `append raw` → `size`. This is safe **only because** `LogConsumer` is the sole
  writer and processes events serially (`_apply_one` awaited one at a time);
  snapshot/SSE paths only read; `write_increment` is dead. If a second concurrent
  writer is ever introduced the read-size-then-append split becomes a race. This
  invariant holds today — it must be asserted in a comment so it is not silently
  broken later.
- **Thread-hop amplification.** Done naively, one log increment becomes up to 4
  `to_thread` round-trips, ×128 per batch. Bounded and acceptable, but see §5 for
  a cheaper shape that also restores append+size atomicity within one hop.

## 4. Missing decisions / questions for Codex

1. **Boundary shape.** Pick one and state it, because acceptance criterion "no
   async path calls the sync helper directly" must be testable:
   (a) async variants beside the sync ones (`async def aread_slice` wrapping
   `asyncio.to_thread`), (b) a small `logs/afiles.py` wrapper module, or
   (c) inline `await asyncio.to_thread(files.x, ...)` at each caller.
   Recommend (a) or (b) — a named async boundary is greppable/spy-able; inline
   `to_thread` is not, making the acceptance criterion hard to test. Keep the
   sync `files.*` core public (unit tests + non-async use it).
2. **How is "async callers use the offloaded boundary" proven?** A true
   event-loop-blocking measurement is flaky in CI. Confirm Codex accepts a spy /
   monkeypatch asserting the async wrapper is invoked (and the sync helper is not
   called directly from the async path) as sufficient proof.
3. **`write_increment`** — confirm it stays out of scope (no async wrapper), since
   it has no live caller. Recommend leaving it sync with a note.

## 5. Suggested scope cuts / sequencing

- **Sequence by leverage.** Do `apply_log_event` (LogConsumer append path) first
  — diagnosis §2 #3 is the "even with no log window open" cause and best explains
  whole-site stalls. Then SSE backfill (+ `await asyncio.sleep(0)` between
  chunks), then the snapshot read, then maintenance `remove`. This front-loads the
  highest-leverage fix so the A/B check can confirm root cause before the rest.
- **Collapse `apply_log_event` disk work into one offloaded call.** Instead of
  `size` + (`append` marker) + `append` raw + `size` as 2–4 separate hops, offload
  a single helper that does marker-append + raw-append + returns
  (physical_start, physical_end) in one thread hop. This cuts thread round-trips
  and keeps append+size atomic within the hop (mitigates the §3 race surface).
- **`remove` is lowest priority** — manual-only, off any hot path. Cheap to
  offload and keeps the "no async path calls sync remove" criterion clean, so keep
  it, but it carries no perf value; don't let it gate the P0.
- Everything else in the brief's Out-of-Scope list (frontend buffering, artifacts,
  cache headers, DB) is correctly deferred and not needed to land this P0.
