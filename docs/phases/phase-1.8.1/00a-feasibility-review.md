# Feasibility Review

## Proposed Direction

- Summary: Phase 1.8.1 is a destructive command-first refactor. Execution templates store a `command` as the authoritative user execution definition. Build artifacts are no longer directly runnable. Schedule overrides may override `command` plus node strategy / node ids only. Scrapy command execution is parsed by the agent from the command string and artifact context; server and web validate the command but do not use `spider/settings/args` as the model or protocol contract.
- Source discussion: User confirmed `command-first`, destructive removal of historical template/schedule `spider/settings/args` fields, and support only for `scrapy crawl ...` in this phase.

## Claude Feedback

### Verdict

- Feasible with changes.

### Blockers

- None.

### Risky Assumptions

- The agent must receive artifact context with the command because `scrapy crawl <spider>` does not include scrapyd `project` or `version`.
- Parser duplication can drift. The implementation should put the authoritative parser/validator in shared Python protocol code for server and agent; the web may mirror it for UX but backend remains authoritative.
- Server validation must be reject-by-default. `shlex.split` is not sufficient by itself because shell metacharacters tokenize as normal arguments.
- Historical task snapshots may still contain `spider/settings/args`; task views must remain tolerant enough not to crash.
- In-flight Redis commands using the old payload shape are incompatible with the new agent. This is acceptable only with a drain-before-deploy note because dopilot is single-instance and not HA.

### Questions

- Should old execution templates be backfilled into commands or left unusable?
- Should old `schedules.overrides` keys be stripped or tolerated?
- Should the grammar support long flags or only short `-a` / `-s`?
- Is `POST /api/v1/artifacts/{id}/run` fully removed with no quick-run replacement?
- What is the new task snapshot shape?

### Suggested Scope Or Sequencing Changes

- Build the shared parser first.
- Then change protocol / agent payload handling.
- Then migrate model and resolver.
- Then remove direct artifact run paths.
- Then update frontend command forms and node selector presentation.

## Codex Decision

- Accepted with Codex decisions below.
- Artifact context is required in every Scrapy run command payload: at minimum artifact `project`, `version`, content hash / sha256, filename, size, and fetch path.
- Migration should best-effort synthesize `command` from existing template `spider/settings/args` before dropping those columns. Rows without a spider may keep `command` NULL if needed for migration safety, but new/updated templates must require a valid command.
- Migration should strip `spider/settings/args` from `schedules.overrides`; command overrides are the only execution-param override in 1.8.1.
- Grammar supports only `scrapy crawl <spider>`, `-a key=value`, and `-s KEY=VALUE`. Quoted values are allowed through tokenizer behavior; split key/value on the first `=`; empty values are allowed; duplicate keys are last-write-wins; long flags are out of scope.
- `POST /api/v1/artifacts/{id}/run` is removed as a runnable entry point. There is no replacement quick-run in this phase.
- New task snapshots store `command`, `build_artifact`, `node_strategy`, `node_ids`, and `overrides`. They must not store `spider/settings/args` as canonical fields.
- For task-list compatibility, server may derive and store `Task.spider` for Scrapy tasks from command validation/parsing, but it is an indexed convenience field rather than the execution model.

## User Escalations

- None. The user explicitly accepted the destructive command-first refactor.

## Resulting Brief Changes

- The implementation brief must call out destructive migration consequences, in-flight Redis command incompatibility, shared parser requirements, artifact context requirements, and removal of direct build-artifact run.
