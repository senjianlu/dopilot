# Acceptance: Log File I/O P0

## Accepted Changes

- Server log body file reads/writes/removes used by async request/background
  paths now go through named async helpers in `logs/files.py`.
- Redis log event application writes marker+raw in one offloaded helper and uses
  returned physical offsets for DB/SSE state.
- Task log snapshot and SSE backfill use async file reads/sizes; SSE backfill
  yields between chunks.
- Manual terminal cleanup offloads log file removal.
- Focused tests were added for the new async boundary and log consumer path.

## Verification

- `py_compile`: pass.
- Focused log tests: 25 passed.
- Full server tests: 325 passed.
- `ruff check apps packages`: pass.
- `git diff --check`: pass.

## Remaining Risk

This is ready to accept as the P0 code fix. A runtime A/B check with an active
log-producing task is still recommended to quantify the user-visible lag
improvement under real disk/log volume.
