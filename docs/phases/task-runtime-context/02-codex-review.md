# Codex Review: Task Runtime Context

## Findings

No blocking findings.

The implementation matches the active brief:

- Runtime context is built on the server after each concrete execution is
  created, so `task_id`, `execution_id`, and `agent_id` are concrete per target.
- Scrapy receives context through per-job Scrapy settings, not process
  environment mutation.
- Python wheel receives context through child-process environment variables at
  the final merge point.
- Platform `DOPILOT_*` values override forged user/task values in the tested
  Scrapy and Python wheel paths.
- No database migration or broad executor refactor was introduced.

## Notes

- The protocol helper keeps carrier conversion centralized and deterministic,
  which avoids divergent JSON/string-map behavior between server and agent.
- `task_type` is retained as the agent runner discriminator while
  `artifact_type` remains the domain/build-artifact discriminator, matching the
  feasibility decision.

## Residual Risk

- Docker behavior is documented only, as intended. The Docker executor must use
  the same `to_env_map()` contract when it is implemented.
- Future custom env support must explicitly reserve `DOPILOT_*` keys globally;
  this task proves the current runtime-context keys win but does not add custom
  env validation because custom env is out of scope.
