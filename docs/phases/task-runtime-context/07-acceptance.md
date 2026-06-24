# Acceptance: Task Runtime Context

## Accepted State

Dopilot now transmits a canonical runtime context to user workloads for the
implemented Scrapy and Python wheel execution paths.

Available fields:

- `DOPILOT_TASK_ID`
- `DOPILOT_EXECUTION_ID`
- `DOPILOT_AGENT_ID`
- `DOPILOT_ARTIFACT_TYPE`
- `DOPILOT_TASK_TYPE`
- `DOPILOT_TASK_SOURCE`
- `DOPILOT_EXECUTION_TEMPLATE_ID`
- `DOPILOT_SCHEDULE_ID`
- `DOPILOT_RUNTIME_CONTEXT`

Scrapy receives these values as per-job Scrapy settings. Python wheel scripts
receive them as process environment variables. In both paths, Dopilot-owned
values override forged `DOPILOT_*` inputs.

## Verified

- Focused runtime-context tests passed.
- Full protocol/server/agent test suite passed: `513 passed`.
- `ruff check apps packages` passed.
- `git diff --check` passed.

## Deferred

- User-defined/custom environment variable support remains out of scope and is
  ready for a follow-up task.
- Docker runtime injection is documented as the future contract but not
  implemented until the Docker executor phase.
- The local `.venv/bin/pytest` launcher has a stale shebang; tests were run via
  `.venv/bin/python -m pytest`, which passed the required targets.
