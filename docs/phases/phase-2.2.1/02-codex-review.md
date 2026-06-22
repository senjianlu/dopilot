# Phase 2.2.1 Codex Review

## Scope Reviewed

- Brief: `docs/phases/phase-2.2.1/00-brief.md`
- Claude report: `docs/phases/phase-2.2.1/01-claude-implementation-report.md`
- Key files:
  - `apps/server/dopilot_server/config/loader.py`
  - `apps/server/dopilot_server/app.py`
  - `apps/agent/dopilot_agent/config/loader.py`
  - `apps/agent/dopilot_agent/main.py`
  - `deploy/docker/Dockerfile`
  - `deploy/docker/docker-compose.yml`
  - `configs/server.docker.toml`
  - `configs/agent.example.toml`
  - `configs/server.example.toml`
  - updated config tests and deployment docs

## Findings

### P0 / Blocking

- None.

### P1 / Must Fix

- None.

### P2 / Should Fix

- Codex adjusted user-facing deploy docs/comments after Claude's implementation
  so default Docker deployment no longer suggests setting `DOPILOT_CONFIG`
  directly. Internal code/tests still support `DOPILOT_CONFIG`, but
  Docker/compose docs now present role default paths plus `DOPILOT_*` env
  overrides as the normal deployment model.

## Test Gaps

- Claude could not run Python/ruff commands because its subprocess permission
  layer denied executing the local virtualenv binaries.
- Codex ran the required commands directly; see
  `docs/phases/phase-2.2.1/05-codex-verification-report.md`.

## Architecture / Docs Gaps

- None remaining.

## Required Claude Follow-Up

- None.
