# Phase 1.8.1 — Claude progress log

## Size class

**Large.** Cross-cutting, destructive refactor touching: shared protocol parser,
server schemas/services/resolver/executor/outbox payload, agent command consumer,
SQLAlchemy model + Alembic migration, removal of direct artifact run, and the
Templates/Schedules web pages + their TS types/tests. Backend + frontend + a
destructive DB migration in one packet.

## Cadence / checkpoints

Update this file at each checkpoint below.

1. [done] Context read + plan.
2. [done] Shared Scrapy command parser/validator in `packages/protocol` + unit tests.
3. [done] Protocol run-payload (`ScrapyRunPayload`: command + artifact) model.
4. [done] Server: model + migration 0008 (add `command`, drop `spider/settings/args`,
   strip schedule override keys).
5. [done] Server: schemas / resolver / templates+schedules services / executor /
   parse_scrapy_params command-first.
6. [done] Remove direct build-artifact run (API + service + web helper + UI).
7. [done] Agent: command consumer parses `command`, resolves project/version from
   artifact context, calls `ScrapydClient.schedule`.
8. [done] Web: Templates + Schedules forms/types/i18n, node-tag-in-select via the
   Element Plus `#tag` slot (no duplicate chips below).
9. [done] Update/extend backend + protocol + agent + web tests.
10. [BLOCKED] Run required commands — program execution (pytest / ruff / pnpm /
    docker / any interpreter) is gated behind per-command approval and is
    auto-declined in this non-interactive run. Commands recorded verbatim in the
    report for the reviewer to run.
11. [done] Implementation report (`01-claude-implementation-report.md`).

## Likely long-running commands

- `corepack pnpm --filter web build` (Vite build).
- `pytest` (full suite) if time permits.
- `docker compose config` (fast) / `make compose-smoke` (slow; only if time).

## Notes / decisions as I go

- Grammar: `scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...`. Tokenize
  with quote support; reject unquoted shell metacharacters and any non-allowlist
  flag/token. Authoritative parser lives in `packages/protocol`; web mirrors for
  UX only.
- Migration best-effort synthesizes `command` from old `spider/settings/args`
  (rows with no spider keep `command` NULL), then drops those columns and strips
  `spider/settings/args` from `schedules.overrides`.
</content>
