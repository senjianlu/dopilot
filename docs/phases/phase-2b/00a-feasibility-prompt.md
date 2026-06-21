# Claude Feasibility Prompt: Phase 2b Python Wheel Shell-Command Runner

You are Claude Code working in the dopilot repository. This is a focused
feasibility validation only. Do not implement application changes.

## Task

Validate the implementation plan for **phase 2b: Python wheel shell-command
runner** after phase 2a has landed.

Phase 2b target:

- Add `python_wheel` `.whl` build artifacts.
- Let users create execution templates bound to those wheel artifacts.
- A template carries an explicit `shell_command`.
- Server dispatches `python_wheel` tasks to agents that advertise the existing
  `script` capability.
- The existing `dopilot-agent` downloads/caches the wheel and runs the shell
  command in the agent container's current Python/environment.
- stdout/stderr are merged into one existing `log` stream.
- Exit code mapping:
  - `0 -> finished`
  - non-zero -> failed
  - cancel -> process-group termination, report canceled
- Cancellation:
  - send SIGTERM to the shell command process group;
  - wait a hard-coded 10 seconds;
  - send SIGKILL to remaining process group;
  - report canceled for `StopIntent.cancel`.

Accepted user decisions:

- Shell commands are allowed; this is an internal platform and phase 2b does not
  add sandboxing.
- No venv in phase 2b.
- Dependencies are not managed by dopilot. Operators must manually install any
  required dependencies into the agent image/container/environment.
- No dependency control or PyPI resolution.
- Existing capability keys stay as-is. Map artifact types at the server
  boundary:

  ```text
  scrapy -> scrapy
  python_wheel -> script
  docker_image -> docker
  ```

- Keep stdout/stderr merged into a single `log` stream for v1.
- Docker/K3s, source/Git builds, dependency management, multi Python versions,
  split stdout/stderr streams, and WebSocket logs are out of scope.

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00b-plan-review.md`
- `docs/phases/phase-2a/03-acceptance-report.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`

Inspect current code as needed, especially:

- `packages/protocol/dopilot_protocol/execution.py`
- `packages/protocol/dopilot_protocol/common.py`
- `packages/protocol/dopilot_protocol/streams.py`
- `apps/server/dopilot_server/services/states.py`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/models/scheduling.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/api/v1/artifacts.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/dopilot_server/services/resolve.py`
- `apps/server/dopilot_server/services/dispatch.py`
- `apps/server/dopilot_server/executors/base.py`
- `apps/server/dopilot_server/executors/registry.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/nodes/service.py`
- `apps/agent/dopilot_agent/config/settings.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/redis/events.py`
- `apps/agent/dopilot_agent/redis/logs.py`
- `apps/agent/dopilot_agent/state/store.py`
- `apps/agent/dopilot_agent/runners/scrapyd.py`
- `apps/agent/dopilot_agent/artifacts/cache.py`
- `apps/web/src/pages/BuildArtifactsPage.vue`
- `apps/web/src/pages/TemplatesPage.vue`
- `apps/web/src/api/types.ts`
- relevant tests under `packages/protocol/tests`, `apps/server/tests`,
  `apps/agent/tests`, and `apps/web/src/**/__tests__`.

Use `rg` to discover references. Do not read or edit `reference/scrapydweb/`.

## Questions To Answer

1. Is phase 2b feasible as a single implementation packet, or should it be split
   further? If split, propose the smallest safe split with acceptance criteria.
2. What exact server/API/model/service/executor surfaces need to change for
   wheel upload, template validation/resolution, and dispatch?
3. Is a DB migration required, or can existing `BuildArtifact`,
   `ExecutionTemplate`, `Task`, and `Execution` structures hold the new data via
   existing JSON/command fields?
4. What protocol payload shape should the agent receive for `python_wheel` run
   commands? Include required keys and optional keys.
5. What agent-side architecture is safest: refactor `CommandConsumer` into a
   runner registry now, or add a narrower type branch first? Explain the risk to
   existing Scrapy behavior.
6. What should "wheel caching" mean without venv/dependency management? Should
   phase 2b cache/download wheel bytes only, install the wheel with
   `pip install --no-deps`, or avoid installation entirely and only execute the
   supplied shell command from a workspace? Make a recommendation consistent
   with the accepted no-venv/no-dependency-control decisions.
7. What exact shell semantics should the brief pin down (`/bin/sh -c`, env
   merge precedence, working directory root, `PYTHONUNBUFFERED`, process group
   lifecycle)?
8. What tests are mandatory before implementation is accepted?
9. What residual risks need user approval beyond the already accepted decisions?
10. What existing docs or comments are stale after the no-venv/no-dependency
    decision and must be updated during implementation?

## Constraints

- Do not implement.
- Do not edit application code.
- You may create or update only:

  ```text
  docs/phases/phase-2b/00a-feasibility-review.md
  docs/phases/phase-2b/claude-progress.md
  ```

- Do not run broad test suites. Read-only shell commands are allowed.
- Do not read or edit `reference/scrapydweb/`.
- Keep the report concise and decision-oriented with file references.

## Expected Report Shape

Use these headings:

```text
# Phase 2b Feasibility Review

## Verdict
## Scope And Split Recommendation
## Server/API Surface
## Protocol Payload
## Agent Architecture
## Wheel Handling Without Venv
## Shell Semantics
## Required Verification
## Docs To Update
## Residual Risks
## Commands Run
```
