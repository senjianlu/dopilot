# Phase 2.2 — Claude Progress

## Size class

**Medium.** Touches config loader/settings, auth posture, two ORM models, two
Alembic migrations, two services, API schemas, the scheduler runner, config
examples + compose + deployment docs, and the matching server tests. No new
subsystems; all changes are additive/hardening within existing seams.

## Update cadence

Update this file at each checkpoint below and before/after any long-running
command (full `pytest`, `pnpm` build).

## Checkpoints

1. [x] Read brief + all required context files.
2. [x] Docs first: requirements decision #12 auth posture, schedule
   enabled/pause wording, deployment doc + config comments.
3. [x] Config + auth hardening: `AuthSettings.disabled`, `enabled` semantics,
   fail-closed in `load_settings`.
4. [x] Env override surface (string/int/bool tables) + typed-value errors.
5. [x] Name uniqueness: ORM `unique=True` + migration 0010 (dedup + constraints)
   + service 409 helpers.
6. [x] Schedule enabled: model + migration 0011 + schemas + service + runner.
7. [x] Update/extend tests.
8. [ ] Run required commands, capture outcomes. **BLOCKED**: sandbox requires
   manual approval for all code execution (pytest/ruff/python/docker). Read-only
   file ops run fine; `pytest …`, `ruff check apps packages`, `python3 -c …` all
   return "This command requires approval". Awaiting approval to run.
9. [ ] Write implementation report (draft written; commands section pending run).

## Likely long-running commands

- `pytest` (full server suite) — minutes.
- `corepack pnpm --filter web test` / `build` — only if API schema change forces
  web updates; run if narrow server tests are insufficient.
- `cd deploy/docker && docker compose config` — fast, but docker may be absent
  in sandbox; record exact failure if so.

## Notes / blockers

- (none yet)
