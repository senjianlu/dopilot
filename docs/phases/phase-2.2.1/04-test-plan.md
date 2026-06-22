# Phase 2.2.1 Test Plan

## Behavior Under Test

- `DOPILOT_ADMIN_API_SECRET` replaces `DOPILOT_TOKEN_SECRET` as the admin API
  secret env.
- `DOPILOT_TOKEN_SECRET` is intentionally not accepted as an alias.
- Server machine tokens fall back to the effective admin API secret when empty.
- Agent machine tokens fall back to `DOPILOT_ADMIN_API_SECRET` when empty.
- Explicit split machine-token envs override the fallback.
- Server/agent role default config paths work without compose `DOPILOT_CONFIG`.
- Docker compose remains valid, keeps Redis password auth, and renders no
  `DOPILOT_CONFIG` service env.

## Unit Coverage

- `apps/server/tests/test_config.py`
  - env rename and removed old alias;
  - machine-token fallback and split-token override;
  - default path precedence.
- `apps/agent/tests/test_config.py`
  - admin-secret fallback for both machine tokens;
  - split-token override;
  - default path precedence.

## Integration Coverage

- Full Python suite across server, agent, and protocol.

## Smoke / Manual Coverage

- `docker compose config` for `deploy/docker/docker-compose.yml`.
- Rendered compose checked for no `DOPILOT_CONFIG` entries and expected
  `DOPILOT_ADMIN_API_SECRET` / `DOPILOT_ADMIN_PASSWORD` service envs.

## Commands Run

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
cd deploy/docker && docker compose config | rg 'DOPILOT_CONFIG|DOPILOT_ADMIN_API_SECRET|DOPILOT_ADMIN_PASSWORD|REDIS_PASSWORD|requirepass'
```

## Results

See `05-codex-verification-report.md`.
