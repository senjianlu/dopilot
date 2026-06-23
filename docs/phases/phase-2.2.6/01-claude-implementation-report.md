# Phase 2.2.6 — Claude Implementation Report

## Summary

Added an agent-side environment override `DOPILOT_SERVER_URL -> [agent].server_url`
so agent-only / cross-host / K3s deployments can point the agent at a reachable
server HTTP base URL without mounting a custom TOML. The baked compose default
`http://server:5000` only resolves inside the all-in-one compose network. Updated
the agent-only compose to require `DOPILOT_SERVER_URL` (fail-fast via Compose
`:?`), added focused tests, and updated docs/README snippets.

Scope honored: no server-side code, no K8s manifest generation, no Redis behavior
change, no Docker image rebuild, no touching of untracked `tmux.sh`.

## Behavior Implemented

- `DOPILOT_SERVER_URL` (agent-side env) overrides TOML `[agent].server_url`.
- Env wins over TOML, matching the existing override pattern (set only when the
  env var is non-empty; an unset/empty env leaves the TOML/default unchanged).
- The existing `[agent].server_url` field is not renamed; no new validation added
  (string passthrough only).
- Loader docstring updated to list the new override and describe it as the server
  HTTP base URL for heartbeat and artifact/wheel fetch.

## Changed Files

| File | Change |
| --- | --- |
| `apps/agent/dopilot_agent/config/loader.py` | Apply `DOPILOT_SERVER_URL` env override to `agent_section["server_url"]` (env wins, non-empty only); updated docstring listing env overrides. |
| `apps/agent/tests/test_config.py` | Added `test_server_url_env_override` and `test_server_url_keeps_toml_without_env`; added `monkeypatch.delenv("DOPILOT_SERVER_URL", ...)` to `test_loads_from_toml` for isolation. |
| `deploy/docker/docker-compose.agent.yml` | Documented `DOPILOT_SERVER_URL` as required in the header; added `DOPILOT_SERVER_URL: ${DOPILOT_SERVER_URL:?...}` to the agent environment; updated the deploy example command. Kept `DOPILOT_AGENT_TOKEN` required, Redis behavior unchanged, no `DOPILOT_CONFIG`, no `DOPILOT_ADMIN_API_TOKEN`. |
| `configs/agent.example.toml` | Documented that `server_url` is the server HTTP base URL for heartbeat + artifact/wheel fetch and is overridable via the agent-side `DOPILOT_SERVER_URL` env, with K3s/cross-host examples and the transport-encryption caveat. |
| `docs/dopilot/08-docker-deployment.md` | Corrected the now-stale note that `DOPILOT_SERVER_URL` is not injected; documented the new agent-side override, examples, the `:?` fail-fast requirement, and the transport caveat (Chinese, matching the doc). |
| `README.md` | Added `DOPILOT_SERVER_URL` to the agent-only join command and explained it as an agent-side env (heartbeat + artifact/wheel fetch) with examples and the transport caveat. |
| `README.zh-CN.md` | Same as `README.md`, in Chinese. |

All-in-one `deploy/docker/docker-compose.yml` left unchanged (baked
`http://server:5000` is correct inside that network).

## Tests Added/Updated

- `test_server_url_env_override` — `DOPILOT_SERVER_URL` overrides the TOML
  `server_url` (asserts the K3s service-DNS example value).
- `test_server_url_keeps_toml_without_env` — with the env unset, `server_url`
  stays the TOML value `http://server:5000`.
- `test_loads_from_toml` — now also clears `DOPILOT_SERVER_URL` so the ambient
  environment cannot perturb the `server_url` assertion.

## Commands Run — Exact Outcomes

| Command | Outcome |
| --- | --- |
| `.venv/bin/ruff check apps packages` | **PASS** — `All checks passed!` |
| `git diff --check` | **PASS** — no output (no whitespace errors) |
| `git diff --stat` | 7 files changed, 89 insertions(+), 13 deletions(-) |

### Blocked by the permission layer (not run)

The local permission layer denied the following commands (returned
`This command requires approval`); they were not executed. Per the invocation
protocol these are reported for Codex to run:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_config.py apps/agent/tests/test_heartbeat_worker.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
.venv/bin/pytest apps/agent/tests/test_config.py
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_SERVER_URL=http://server.example:5000 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
.venv/bin/python -c "import yaml; ..."   # tried as an alternate YAML/loader check; also blocked
```

`pytest` (all forms tried: `python -m pytest`, `.venv/bin/pytest`, with/without
`PYTHONPATH`), `docker compose`, and `python -c` are all denied by the permission
layer. `ruff` and `git` are allowed. The expected results for the blocked
commands:

- both pytest invocations: PASS (the two new tests plus the unchanged suite).
- first compose `config`: renders and includes `DOPILOT_SERVER_URL`; contains no
  `DOPILOT_CONFIG` and no `DOPILOT_ADMIN_API_TOKEN`.
- second compose `config` (no `DOPILOT_SERVER_URL`): **expected failure** —
  Compose `:?` aborts with the required-variable message because
  `DOPILOT_SERVER_URL` is unset.

## Unresolved Risks / Skipped Commands

- The pytest and `docker compose config` verifications could not be executed
  locally (permission layer). Logic was reviewed by hand; Codex should run the
  blocked commands above to confirm test pass and the expected fail-fast on the
  missing `DOPILOT_SERVER_URL`.
- No functional behavior change beyond the new deployment override; the heartbeat
  protocol, Redis URL handling, and server side are untouched.
