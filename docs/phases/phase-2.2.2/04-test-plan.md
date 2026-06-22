# Test Plan

## Targeted Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/agent/tests/test_config.py
```

Covers:

- static `admin_api_token` direct admin auth;
- login-issued opaque token compatibility;
- `DOPILOT_ADMIN_API_TOKEN` env override;
- removed `DOPILOT_ADMIN_API_SECRET` no-op behavior;
- server and agent machine-token fallback behavior;
- short-token loader validation.

## Full Regression

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
git diff --check
```

Full pytest is warranted because auth dependencies guard many API routes and
config loading affects both server and agent startup.

## Additional Checks

```bash
cd deploy/docker && docker compose config | rg 'DOPILOT_CONFIG|DOPILOT_ADMIN_API_SECRET|DOPILOT_ADMIN_API_TOKEN'
```

Expected:

- no `DOPILOT_CONFIG`;
- no `DOPILOT_ADMIN_API_SECRET`;
- four `DOPILOT_ADMIN_API_TOKEN` entries (server + three agents).
