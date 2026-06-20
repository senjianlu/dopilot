# Phase 1.8.1 Codex Acceptance Summary

## Outcome

Accepted after Codex review, Claude fixes, and Codex-side verification.

Phase 1.8.1 implements the destructive command-first refactor:

- Build artifacts are no longer directly runnable; runs go through execution
  templates.
- Execution templates store `command` as the authoritative run input.
- Template and schedule request/response models no longer expose historical
  template/schedule `spider` / `settings` / `args` fields.
- Schedules can override only `command`, `node_strategy`, and `node_ids`.
- The Scrapy command grammar for this phase is limited to:
  `scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...`.
- Server-side validation rejects invalid commands and commands whose spider is
  not advertised by the bound build artifact.
- Blank schedule command overrides are treated as absent and inherit the
  template command.
- The agent receives `command` plus build-artifact context, parses the command,
  and schedules Scrapyd from the parsed spider/args/settings.
- Web template creation and schedule creation expose command inputs and no
  spider selector; node selection tags render status color inside the select
  input without duplicate chips below.
- Governance constraints now explicitly forbid Codex from manually stopping a
  running Claude subprocess without user approval.

## Verification

Codex ran:

```text
.venv/bin/pytest
368 passed

corepack pnpm --filter web test
8 files passed, 28 tests passed

corepack pnpm --filter web build
passed

.venv/bin/ruff check apps packages
All checks passed

cd deploy/docker && docker compose config
passed
```

## Notes

- Web unit tests still emit existing Vue test warnings for unresolved
  `v-loading`; they do not fail tests and were not introduced by phase 1.8.1.
- The production build still emits existing dependency/chunk-size warnings; the
  build completes successfully.
