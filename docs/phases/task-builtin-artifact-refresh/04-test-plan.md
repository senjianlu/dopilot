# Test Plan: Built-In Artifact Refresh

## Coverage

- Import built-in Scrapy and Python wheel artifacts from a temporary built-in
  root into a temporary artifact store.
- Repeated same-content import is a no-op for row count and manifest content.
- Changed built-in bytes create an additional hash/artifact.
- Same-hash existing user row metadata is preserved while missing store files
  are repaired.
- Invalid built-in artifact fails startup.
- Static assertions lock `dopilot_clock` default duration/logging source.
- Static wheel assertion locks the rebuilt `dopilot-demo` env logging payload.

## Commands

```bash
PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest apps/server/tests/test_builtin_artifacts.py
PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest packages/protocol/tests apps/server/tests apps/agent/tests
.venv/bin/ruff check apps packages
git diff --check
cd deploy/docker && docker compose config
```
