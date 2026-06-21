# Phase 2b Page-Level E2E — Codex Review

Status: accepted after Codex follow-up fix.

## Review Result

Claude completed the requested Docker + browser page-level validation and added
coverage for both execution families:

- Scrapy: artifact upload, template creation, template run, task detail, three
  agent executions, log markers.
- Python wheel: clean-volume built-in wheel listing, template creation with a
  shell command, run to completion on three script-capable agents, log markers
  from the demo wheel.

Codex reviewed the changes and found one stale smoke-oracle issue in
`scripts/smoke-phase1.sh`: the script still tested the removed direct artifact
run endpoint (`POST /api/v1/artifacts/{id}/run`). That endpoint was intentionally
removed before phase 2b, and server tests already assert that the route is gone.
Codex removed that obsolete case from the Scrapy smoke script and renumbered the
remaining schedule/node-selection cases.

No remaining blocking findings.

## Files Reviewed

- `deploy/docker/Dockerfile`
- `configs/agent.example.toml`
- `scripts/smoke-phase1-ui.sh`
- `scripts/smoke-phase1.sh`
- `apps/web/e2e/helpers/ui.ts`
- `apps/web/e2e/specs/phase1-ui.spec.ts`

## Docker / Browser Verification

Codex re-ran the browser smoke on the current worktree:

```bash
scripts/smoke-phase1-ui.sh
```

Result: passed.

- Clean-volume Docker stack built and started.
- Three agents reached healthy + schedulable with both `scrapy` and `script`
  capabilities.
- Playwright Chromium ran 9 specs.
- Result: `9 passed (22.3s)`, `UI SMOKE PASSED`.
- The script teardown ran `docker compose down -v`.

Codex also re-ran the backend Scrapy smoke after removing the obsolete direct-run
case:

```bash
scripts/smoke-phase1.sh
```

Result: passed.

- Scrapy template dispatch completed across the three agents.
- Schedule trigger-now, offline exclusion, heartbeat-timeout exclusion, and
  soft-delete exclusion all passed.
- Result: `passed: 53   failed: 0`, `SMOKE PASSED`.
- The script teardown ran `docker compose down -v`.

Post-run inspection:

```bash
docker ps --format '{{.Names}} {{.Status}}'
```

Result: no running containers.

## Host Verification

Codex re-ran the phase-level checks on the current worktree:

| Command | Result |
| --- | --- |
| `.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests` | `427 passed` |
| `corepack pnpm --filter web test` | `45 passed` |
| `corepack pnpm --filter web build` | passed; Vite emitted only existing bundle-size / PURE-comment warnings |
| `.venv/bin/ruff check apps packages` | `All checks passed!` |
| `docker compose -f docker-compose.yml -f docker-compose.e2e.yml config` from `deploy/docker` | passed |
| `git diff --check` | passed |

## Residual Notes

- The browser smoke uses `DOPILOT_DEMO_URL=http://server:5000/api/v1/health` for
  the demo wheel to avoid external-network flakiness. The wheel fixture still
  defaults to `https://httpbin.org/headers` outside the smoke.
- No screenshots/videos/traces were produced because Playwright is configured to
  retain them only on failure.
- `.claude/` remains an untracked local Claude state directory and was not
  modified by Codex.
