# Task Runtime Context Feasibility Review

## 1. Verdict

Feasible with changes.

The proposed contract and carriers fit the current architecture: Scrapy can
receive Dopilot context through per-job Scrapy settings, and Python wheel tasks
can receive the same canonical fields through the child process environment.
No database migration is needed.

## 2. Blocking Issues

None.

## 3. Risky Assumptions

- Server payload construction currently happens before the per-node execution
  loop in both `ScrapydExecutor` and `PythonWheelExecutor`. Runtime context
  needs `execution_id` and `agent_id`, so payload construction must move inside
  the loop after `create_execution(...)`.
- `DOPILOT_RUNTIME_CONTEXT` must use deterministic JSON serialization. Do not
  rely on incidental Pydantic key order in tests; use one shared helper with
  stable field order or `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
- Python wheel env precedence must be enforced at the last merge point. The
  runner currently applies payload `env` after setting platform defaults, so the
  runtime context map should be applied after payload/user env, or reserved
  `DOPILOT_*` keys should be filtered before the runner receives env.
- Scrapy settings are the correct carrier, but user command `-s DOPILOT_...`
  values must be overwritten after command parsing and before
  `ScrapydClient.schedule(...)`.
- Future custom env support must reserve `DOPILOT_*` globally for all workload
  types. This task should add the reserved-key behavior now even though custom
  env UI is out of scope.

## 4. Missing Decisions Or Questions For Codex

- Confirm `task_type` in runtime context means the existing wire runner
  discriminator (`scrapy`, `python_wheel`, future Docker value), while
  `artifact_type` remains the product/domain artifact type.
- Confirm nullable IDs use empty strings in individual keys for all carriers,
  including Scrapy settings. This is workable and matches the brief.
- Decide whether the shared protocol helper should expose both
  `to_env_map()` and `to_scrapy_settings()`. They can return the same string map
  today, but separate method names make the carrier intent explicit.

## 5. Suggested Scope Cuts Or Sequencing Changes

- Keep Docker to documentation only in this packet.
- Implement one protocol `DopilotRuntimeContext` model/helper first, then use it
  from server executors. Avoid duplicating map/JSON construction in server and
  agent code.
- Build runtime context on the server, per execution, and include it in the run
  payload as `runtime_context`. Let the agent only convert/inject the already
  canonical payload. This keeps Task/Execution/source/schedule/template truth at
  the server boundary.
- Add focused tests before broader regression runs: protocol serialization,
  Scrapy outbox payload, wheel outbox payload, Scrapy settings injection with
  user override blocked, and wheel env injection with user override blocked.
