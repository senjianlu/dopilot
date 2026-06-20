# Phase 1.8.1 Brief

## Goal

Make execution templates command-first. A build artifact is no longer directly runnable; users must create an execution template with a command, then run that template or schedule it. This phase is a destructive refactor that removes template/schedule `spider/settings/args` as product and protocol concepts.

## Context

Relevant files and decisions:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-1.8/00-brief.md`
- `docs/phases/phase-1.8.1/00a-feasibility-review.md`
- `packages/protocol/dopilot_protocol/`
- `apps/server/dopilot_server/{api,models,services,executors,redis}/`
- `apps/agent/dopilot_agent/{redis,runners,scrapyd}/`
- `apps/web/src/pages/{BuildArtifactsPage.vue,TemplatesPage.vue,SchedulesPage.vue}`

Architecture constraints:

- Phase 1.8.1 supports only `artifact_type="scrapy"` at runtime.
- The only command grammar in this phase is:

```bash
scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...
```

- Commands are not shell commands. They must be tokenized and interpreted by explicit allowlist grammar. No shell execution, pipes, redirects, `;`, `&&`, env prefixes, or other Scrapy subcommands.
- The web validates commands for user experience. The backend remains authoritative. The agent validates/parses again before execution.
- Server remains the database owner. Agent never connects to PostgreSQL.
- Redis is transport only. In-flight old run commands are incompatible with this refactor; deployment should drain active/queued commands first.

## In Scope

- Add a shared Python command parser/validator for Scrapy commands under `packages/protocol`.
- Change server-side template and schedule run resolution to use `command` as the canonical execution input.
- Change Redis run command payloads to carry `command` plus artifact context instead of `spider/settings/args` as the protocol contract.
- Change agent Scrapy command handling to parse `command`, resolve project/version from artifact context, and call the existing local scrapyd client.
- Remove build-artifact direct run from API and web.
- Add a destructive Alembic migration:
  - add `execution_templates.command`;
  - best-effort backfill command from old `spider/settings/args`;
  - drop `execution_templates.spider`, `execution_templates.settings`, and `execution_templates.args`;
  - strip `spider/settings/args` keys from `schedules.overrides`.
- Update API schemas and TS types so execution templates expose `command`; schedule overrides expose `command`, `node_strategy`, and `node_ids`.
- Update Templates and Schedules pages:
  - users input command instead of selecting spider;
  - schedules can override command using the same command input style;
  - node selector tag status color appears inside the select input without duplicate chips below.
- Keep historical tasks readable when old snapshots contain `spider/settings/args`.
- Preserve `Task.spider` as a derived/indexed convenience for Scrapy task filtering if useful, but do not use it as the execution model.

## Out Of Scope

- Python wheel execution.
- Docker image execution.
- Arbitrary shell command execution.
- Long Scrapy flags such as `--set` or custom non-`crawl` Scrapy commands.
- One-off direct build-artifact runs or quick-run replacement UX.
- Full preservation of legacy template/schedule behavior beyond migration not crashing and best-effort command backfill.
- Multi-replica / HA deploy compatibility.

## Required Implementation Order

1. Implement shared Scrapy command parser/validator in `packages/protocol` with unit tests.
2. Update server schemas/services/resolver/executor/outbox payload construction to use command-first semantics.
3. Update agent command consumer / Scrapy runner path to parse command and call existing `ScrapydClient.schedule`.
4. Add Alembic migration and update SQLAlchemy model.
5. Remove direct build-artifact run endpoint, service usage, web API helper, and UI button.
6. Update Templates and Schedules web forms/types/tests.
7. Update backend and protocol tests for command-first behavior.
8. Run targeted verification, then broaden to web tests/build and compose config as practical.

## Acceptance Criteria

- A user can upload/list a Scrapy egg, create an execution template with `scrapy crawl phase1`, run the template, and dispatch a Redis command carrying `command` and artifact context.
- The agent parses `scrapy crawl phase1 -a key=value -s LOG_LEVEL=DEBUG` and calls scrapyd with spider `phase1`, args `{key: value}`, and settings `{LOG_LEVEL: DEBUG}`.
- Invalid commands are rejected by server with structured API errors and by frontend before submit.
- A schedule can inherit template command or override it entirely with a new command.
- Schedule command override fully replaces the template command; it does not merge args/settings.
- Build artifacts cannot be directly run through web or API.
- ExecutionTemplate API responses contain `command` and no longer expose `spider/settings/args`.
- Schedule override API shape contains only `command`, `node_strategy`, and `node_ids`.
- Existing task detail/list views do not crash on historical task snapshots.
- Node selection tags display status color inside the select input, with no duplicate tag rendering below.
- No code imports or copies from `reference/scrapydweb/`.

## Required Tests

- Unit tests:
  - parser accepts valid `scrapy crawl` forms;
  - parser rejects non-crawl commands, shell metacharacters, missing spider, malformed `-a` / `-s`;
  - parser handles quoted values, `=` in values, empty values, and duplicate keys last-write-wins.
- Server tests:
  - template create/update requires and validates command;
  - template run dispatches command + artifact context;
  - schedule create/update accepts command override and rejects old `spider/settings/args` override keys;
  - schedule trigger/timer uses override command when present and template command otherwise;
  - direct artifact run endpoint is unavailable;
  - task views tolerate old snapshots.
- Agent/protocol tests:
  - command payload schema round-trips;
  - agent parses command and calls scrapyd with expected spider/settings/args;
  - agent reports structured failure for invalid command.
- Frontend tests:
  - template dialog uses command input and no spider select;
  - schedule dialog supports command override;
  - invalid commands block submit;
  - node tags are rendered once in the input with status styling.
- Smoke/manual checks:
  - Update existing Phase 1 UI/E2E assumptions away from direct artifact run and read-only command.

## Required Commands

Use the narrowest commands first, then broaden:

```bash
pytest packages/protocol/tests apps/agent/tests apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py apps/server/tests/test_executions.py apps/server/tests/test_resolve.py
corepack pnpm --filter web test
corepack pnpm --filter web build
ruff check apps packages
cd deploy/docker && docker compose config
```

Run broader checks if the narrow set passes and time permits:

```bash
pytest
make compose-smoke
```

## Risks To Watch

- In-flight old Redis run commands will not be compatible with the new agent payload. Deploy only after draining old queued/running commands.
- Dropping template columns is destructive. The migration should best-effort synthesize `command` first, but old decomposed values are not preserved after upgrade.
- Server and agent parsers must not drift. Prefer one shared Python parser in `packages/protocol`.
- Frontend parser is UX only and may mirror the backend grammar; backend must remain authoritative.
- Element Plus per-tag status styling inside a multi-select may require a custom tag slot or small shared component rather than a CSS-only change.
