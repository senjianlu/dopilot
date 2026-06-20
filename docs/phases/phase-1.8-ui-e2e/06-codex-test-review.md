# 06 · Phase 1.8 UI E2E — Codex Test Review

## Codex-Rerun Commands

```bash
scripts/smoke-phase1-ui.sh
```

Result: PASS. The script cleaned compose volumes, built the images, started one
server plus three agents, waited for three healthy schedulable nodes, ran
Playwright Chromium against `http://localhost:5000`, and tore the stack down.

Browser result:

```text
7 passed (19.7s)
UI SMOKE PASSED
```

```bash
corepack pnpm --filter web test
```

Result: PASS.

```text
Test Files  8 passed (8)
Tests       23 passed (23)
```

```bash
corepack pnpm --filter web build
```

Result: PASS.

```text
vue-tsc -b && vite build
built in 8.74s
```

```bash
docker ps -a
```

Result: no containers remained after smoke teardown.

## Claude-Reported Commands Reviewed

Claude also reported the broader regression set passing:

- `.venv/bin/ruff check apps packages`
- `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider` with 317 passed
- `scripts/smoke-phase1.sh` with 58 passed, 0 failed

Codex independently reran the page-level smoke requested by the user, plus web
unit tests and production build.
