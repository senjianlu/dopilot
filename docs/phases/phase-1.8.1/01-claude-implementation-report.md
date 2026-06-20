# Phase 1.8.1 — Claude Implementation Report

Command-first execution templates. A build artifact is no longer directly
runnable; users create an execution template carrying a `scrapy crawl ...`
command, then run or schedule that. The legacy template/schedule
`spider`/`settings`/`args` fields are removed as product and protocol concepts.

## Summary of approach

- One **authoritative Scrapy command parser/validator** lives in the shared
  `packages/protocol` and is imported by both server and agent — no parser drift.
  The web ships a UX-only mirror.
- The Redis run payload is **command-first**: it carries `command` + the
  build-artifact `artifact` context (project/version/sha256/filename/fetch_path),
  not decomposed `spider/settings/args`. The agent parses the command and resolves
  project/version from the artifact context, then calls the existing
  `ScrapydClient.schedule`.
- A schedule override may set only `command` / `node_strategy` / `node_ids`; a
  `command` override **fully replaces** the template command (no merge).
- Direct build-artifact run (API + service + web helper + UI) is removed.
- A destructive Alembic migration adds `execution_templates.command`, best-effort
  backfills it from the legacy decomposed columns, drops them, and strips
  `spider/settings/args` from `schedules.overrides`.

## Changed files by area

### Shared protocol (`packages/protocol`)
- **`dopilot_protocol/scrapy_command.py`** (new) — the authoritative parser:
  `parse_scrapy_command` / `is_valid_scrapy_command` / `build_scrapy_command`,
  `ParsedScrapyCommand`, `ScrapyCommandError` (`code="command.invalid"`,
  `message_key="errors.invalidCommand"`, structured `detail`). Grammar:
  `scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...`. Quote-aware
  tokenizer; reject-by-default of unquoted shell metacharacters and any
  non-allowlist flag/token.
- **`dopilot_protocol/execution.py`** — added `ScrapyRunPayload` (command +
  artifact + task_type); updated `ExecutionRunRequest` docstring to command-first.
- **`dopilot_protocol/__init__.py`** — export the new symbols.

### Server (`apps/server/dopilot_server`)
- **`models/scheduling.py`** — `ExecutionTemplate`: dropped `spider`/`settings`/
  `args`, added nullable `command`; updated `Schedule.overrides` docstring.
- **`migrations/versions/0008_command_first_templates.py`** (new) — destructive
  migration (see below).
- **`api/v1/schemas.py`** — `RunOverrides` now `{command, node_strategy, node_ids}`
  with `extra="forbid"`; removed `ArtifactRunRequest`; `ExecutionTemplateView` /
  `ExecutionTemplateCreateRequest` (command required) / `ExecutionTemplateUpdateRequest`
  are command-first.
- **`services/resolve.py`** — `OVERRIDE_KEYS=(command,node_strategy,node_ids)`;
  `validate_command`; `sanitize_overrides` validates a command override;
  `resolve_run` parses the (override-or-template) command, derives `spider`, and
  emits a command-first `params`/snapshot.
- **`services/templates.py`** — create/update/validate/defaults/view are
  command-first.
- **`services/executions.py`** — `parse_scrapy_params` re-validates the command at
  the dispatch boundary and returns `{command, project, spider(derived), version,
  artifact}`.
- **`executors/scrapyd.py`** — run payload built from `ScrapyRunPayload(command,
  artifact)`.
- **`services/dispatch.py`** — removed `run_direct_artifact`; docstring updated.
- **`api/v1/artifacts.py`** — removed `POST /artifacts/{id}/run` and its imports.

### Agent (`apps/agent/dopilot_agent`)
- **`redis/commands.py`** — `_handle_run` parses `payload["command"]` with the
  shared parser, resolves project/version from `payload["artifact"]`, fails with a
  structured `command_invalid` terminal on a missing/invalid command or missing
  artifact project, ensures the egg cache only when the artifact carries a
  fetchable hash, and schedules via the unchanged `ScrapyRunner`/`ScrapydClient`.

### Web (`apps/web`)
- **`src/utils/scrapyCommand.ts`** (new) — UX-only command checker mirroring the
  grammar (`checkScrapyCommand` / `isValidScrapyCommand`).
- **`src/api/types.ts`** — `ExecutionTemplate`/`CreateExecutionTemplateRequest`
  use `command`; `ScheduleOverrides` = `{command, node_strategy, node_ids}`;
  removed `ArtifactRunRequest`.
- **`src/api/artifacts.ts`** — removed `runBuildArtifact`.
- **`src/pages/BuildArtifactsPage.vue`** — removed the direct-run column/handler.
- **`src/pages/TemplatesPage.vue`** — command text input with inline UX validation
  (blocks submit), default command from the artifact's first spider; node tags get
  status colour **inside** the select via the Element Plus `#tag` slot, removing
  the duplicate chips below the input; table shows the command.
- **`src/pages/SchedulesPage.vue`** — optional command-override input with UX
  validation; node-override tags coloured via the `#tag` slot.
- **`src/i18n/locales/en.ts` / `zh.ts`** — command/override labels, a
  `commandErrors` section, and an `errors.invalidCommand` entry.

## Implementation notes

- **Parser security.** `shlex` alone is insufficient (metacharacters tokenize as
  ordinary args), so the parser first rejects any unquoted shell metacharacter via
  a quote-state scanner, then tokenizes (quote-aware) and checks each token against
  the grammar. A metacharacter inside quotes is a literal value (never executed —
  the agent passes args/settings to scrapyd as structured form fields, not a
  shell). Only `-a` / `-s` flags are accepted; `--set`, `-o`, attached
  `-akey=value`, a second spider, etc. are rejected.
- **Artifact context is mandatory** in the run payload because `scrapy crawl
  <spider>` names no scrapyd project/version. `resolve_run` puts the artifact
  descriptor in `params["artifact"]`; the executor copies it into the payload; the
  agent reads project/version from it.
- **`Task.spider` preserved** as a derived/indexed convenience: it is parsed out of
  the command at resolve time and copied onto the task row, backing the existing
  task-list spider filter. It is not the execution model.
- **Historical tasks** keep `params`/`template_snapshot` verbatim; views read them
  as opaque maps, so old snapshots with `spider/settings/args` still render.
  `TASK_SOURCE_DIRECT` (`direct_artifact`) remains a readable historical value.
- **Schedule command override fully replaces** the template command:
  `command = overrides.command or template.command` — no arg/setting merge.

## Migration (destructive)

`0008_command_first_templates.py`:
1. add nullable `execution_templates.command`;
2. best-effort backfill: `scrapy crawl <spider>` + ` -a k=v` (from `args`) +
   ` -s K=V` (from `settings`) via `jsonb_each_text`; rows with no spider keep
   `command` NULL (migration safety);
3. drop `execution_templates.spider` / `settings` / `args`;
4. strip `spider`/`settings`/`args` keys from `schedules.overrides`.

Destructive consequences (also in the brief Risks): decomposed values are not
recoverable after the drop; synthesized commands do **not** shell-quote values
containing whitespace; in-flight old Redis run commands are incompatible with the
new agent payload — drain active/queued commands before deploying. The SQLite test
DB is built from the ORM models (not this migration), so the model change alone
covers the test suite.

## Tests added / updated

Added:
- `packages/protocol/tests/test_scrapy_command.py` — accepted forms; quoting / `=`
  in value / empty value / duplicate-key last-write-wins; rejection of non-crawl,
  unsupported flags, missing spider/value, malformed pairs, shell metacharacters,
  unbalanced quotes; quoted-metacharacter-allowed; error envelope; `build_*`
  round-trips; `ScrapyRunPayload` round-trip.
- Agent `test_command_consumer.py` — `test_run_parses_command_args_and_settings`
  (asserts spider/args/settings reach scrapyd) and
  `test_run_invalid_command_emits_failed`.
- Server `test_executions.py` — `test_run_carries_artifact_context_in_payload`,
  `test_direct_artifact_run_endpoint_removed`.
- Server `test_resolve.py` — command override fully-replaces, invalid/missing
  command raises, sanitize rejects invalid command override.
- Server `test_schedules.py` — command-override applied; legacy override keys → 422;
  invalid command override → 400.
- Web `TemplatesPage.spec.ts` — command-payload submit, default-command-on-open,
  invalid-command blocks submit, `nodeTagType` colours + no `.node-chips`.
- Web `SchedulesPage.spec.ts` — command-override submit + invalid-override blocks
  submit.

Updated to command-first (no behavioral regression): server `test_templates.py`,
`test_executions.py`, `test_executions_pagination.py`, `test_stats_nextrun.py`,
`test_scheduler_runner.py`; agent `tests/conftest.py` (FakeScrapyd now captures the
schedule form so args/settings can be asserted); web TemplatesPage/SchedulesPage
sample fixtures; the Playwright `e2e/specs/phase1-ui.spec.ts` (artifacts page no
longer runs; template dialog uses an editable command input).

## Commands run — exact outcomes

**Blocked.** Every program-execution command in this environment (any Python
interpreter, `pytest`, `ruff`, `corepack pnpm`, `docker compose`) returns
`This command requires approval` and is auto-declined in this non-interactive run.
Read-only shell commands (`ls`/`grep`/`git`) run fine; interpreter/binary execution
does not. No test/lint/build/compose command could therefore be executed, so no
pass/fail can be reported from this run.

Smallest next action — run these (verbatim from the brief) in an approved shell:

```bash
# narrow first
.venv/bin/pytest packages/protocol/tests apps/agent/tests \
  apps/server/tests/test_templates.py apps/server/tests/test_schedules.py \
  apps/server/tests/test_scheduler_runner.py apps/server/tests/test_executions.py \
  apps/server/tests/test_resolve.py
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
# then broaden
.venv/bin/pytest
make compose-smoke
```

The work was self-reviewed against these instead of an executed run:
- grepped the server/web trees for every removed symbol (`ArtifactRunRequest`,
  `run_direct_artifact`, `runBuildArtifact`, template `spider/settings/args`,
  `_merge_str_map`, the direct-run endpoint) — no stale references remain;
- updated every server test that posted to the removed `/artifacts/{id}/run` or
  created a template with `spider` (`test_executions*`, `test_stats_nextrun`,
  `test_scheduler_runner`, `test_schedules`, `test_templates`);
- confirmed the dispatcher reads `task_type` from the payload (so
  `ScrapyRunPayload.task_type` keeps the wire seam intact);
- confirmed the agent skips cache-ensure when the artifact has no fetchable hash so
  the plain `_run_cmd` fixtures (project-only context) still schedule.

## Known risks / incomplete items

- **No executed verification.** Because program execution is gated, the suites,
  `ruff`, the web build (`vue-tsc`), and `docker compose config` were not run. The
  highest-residual-risk item is the web `vue-tsc` typecheck of the Element Plus
  `#tag` slot props (`item.value` / `item.currentLabel`); the slot is used per the
  Element Plus 2.14 API (`{ data, deleteTag }`), but this should be confirmed by
  `corepack pnpm --filter web build`.
- **Migration backfill is best-effort** and does not shell-quote whitespace values;
  rows with no spider keep `command` NULL by design. Operators must drain in-flight
  Redis run commands before deploying (old payload shape is incompatible).
- **UX parser is a mirror, not the authority.** Intentional per the brief; the
  server and agent both re-validate with the shared parser.
