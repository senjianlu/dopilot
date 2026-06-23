# Task Brief: Log File I/O P0

## Goal

Reduce whole-site UI/API stalls caused by synchronous server-side log file I/O
running on the single `dopilot-server` asyncio event loop.

The server remains single-process / `uvicorn workers=1`. The change must keep
the current Redis log stream -> server file store -> PostgreSQL log index ->
server-to-web SSE architecture, but move blocking log body file operations out
of the event loop.

## Context

Relevant files and decisions:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2b/00-brief.md`
- `/tmp/dopilot-ui-lag-diagnosis.md`
- `apps/server/dopilot_server/logs/files.py`
- `apps/server/dopilot_server/api/v1/tasks.py`
- `apps/server/dopilot_server/services/logs.py`
- `apps/server/dopilot_server/redis/consumers.py`
- `apps/server/dopilot_server/services/maintenance.py`
- Existing server tests under `apps/server/tests/`

Architecture constraints:

- `dopilot-server` is intentionally single-instance and single-worker.
- PostgreSQL remains the business source of truth and stores only log
  index/offset/status. Log bodies remain on the server filesystem.
- Redis remains a transport/message bus, not a durable business database.
- Server-to-web realtime logs continue to use SSE, not WebSocket.
- Do not fetch, vendor, copy, or import upstream scrapydweb code.

## In Scope

- Add a named async-safe boundary for server log body file operations so callers
  in async request handlers/background loops use thread offload or equivalent.
  Preferred shape: async variants or narrow async helpers in
  `apps/server/dopilot_server/logs/files.py` next to the existing synchronous
  helpers. Do not scatter inline `asyncio.to_thread(files.x, ...)` calls across
  request/service modules.
- Update log snapshot and SSE stream backfill paths to avoid direct synchronous
  `read_slice`, `tail_screen`, and `size` calls on the event loop.
- Update Redis log event application so append/size work does not run directly
  on the event loop. Collapse the per-increment disk work into one offloaded
  helper where practical, returning the physical start/end offsets needed for
  DB and SSE updates.
- Add an explicit scheduler yield between SSE backfill chunks so large backfills
  do not monopolize the event loop.
- Update manual log cleanup if it is currently called from async server paths and
  uses synchronous remove operations.
- Preserve existing log offset semantics, gap-marker behavior, SSE event ids,
  file paths, and response payload shapes.
- Add focused regression tests that prove async callers use the offloaded log
  file boundary and preserve existing behavior.

## Out Of Scope

- Frontend log viewer buffering, virtualization, batching, or layout changes.
- Artifact list/upload performance work.
- Static asset caching headers.
- Database query optimization.
- Redis stream topology, consumer group semantics, or multi-worker/server HA.
- Changing log file storage location or moving log bodies into PostgreSQL.
- Broad refactors such as a new log storage service unless narrowly needed.

## Required Implementation Order

1. Identify every async server call path that touches `dopilot_server.logs.files`
   synchronous file operations.
2. Introduce a minimal async wrapper layer or async function variants for
   `size`, `read_slice`, `tail_screen`, `append`, and `remove` as needed. Keep
   existing synchronous helpers for non-async use and unit-level semantics.
3. Convert async request/background paths to use the async boundary.
4. For `apply_log_event`, prefer one offloaded write helper for marker+raw
   append and final size instead of several thread round-trips. Add a short
   comment documenting the current single-writer invariant: Redis `LogConsumer`
   serially awaits `_apply_one`; snapshot/SSE paths only read.
5. Add a scheduler yield between SSE backfill chunks.
6. Add or update focused tests.
7. Run the required commands and record exact outcomes.

## Acceptance Criteria

- No `async def` request handler/background consumer path directly calls
  synchronous log body read/write/size/remove helpers.
- `GET /api/v1/tasks/{task_id}/logs` keeps the same response shape and offset
  behavior while using the async file boundary.
- `GET /api/v1/tasks/{task_id}/logs/stream` keeps first-screen tail, backfill,
  event id, dedupe, completion, and heartbeat behavior while using the async
  file boundary.
- Redis log consumer application preserves append, duplicate-drop, gap marker,
  `last_pulled_offset`, `size_bytes`, `final_offset`, and SSE publish behavior.
- Manual maintenance cleanup still removes log files without blocking the event
  loop.
- The async boundary is testable by importing/monkeypatching named async helpers;
  tests do not rely on flaky wall-clock event-loop blocking measurements.
- Existing Scrapy and Python wheel behavior is unchanged.

## Required Tests

- Unit tests for the async file boundary preserving `size`, `append`,
  `read_slice`, `tail_screen`, and `remove` semantics.
- Server API or service tests covering:
  - log snapshot reads still return expected offsets/content;
  - SSE stream backfill still emits first-screen/backfill data and completion;
  - `apply_log_event` still writes normal increments and gap markers correctly.
- If direct API/SSE tests are impractical, document why and add the narrowest
  equivalent service-level tests.

## Required Commands

Use narrow commands first, then broaden only if shared behavior changed.

```bash
pytest apps/server/tests
ruff check apps packages
```

If web files are not touched, `corepack pnpm --filter web test` is not required.

## Risks To Watch

- Accidentally changing server-file physical offset semantics while offloading
  I/O.
- Reading the file size and appending in separate offloaded calls may preserve
  current behavior, but do not introduce concurrent writes to the same log file.
  The current single log consumer serializes Redis log events; keep that
  assumption intact.
- `asyncio.to_thread` uses the default executor. Keep offloaded work bounded and
  avoid spawning per-byte or per-line tasks.
- File reads still include UTF-8 decoding work. Moving this off the event-loop
  thread is the P0 goal, but runtime A/B or slow-callback checks may still be
  needed to prove the user-visible lag is fully resolved under real log volume.
- Avoid wrapping database work in thread offload. Only file-system work belongs
  behind the async boundary.
