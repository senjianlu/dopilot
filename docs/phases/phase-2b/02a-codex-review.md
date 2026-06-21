# Phase 2b Packet 1 Codex Review

## Verdict

Accepted for packet 2b-1. I found no blocking code-review issues after reviewing
the server/protocol/web diff and rerunning the required checks locally.

Packet 2b-1 is dispatch-ready only. Agent-side wheel download/install/subprocess
execution remains packet 2b-2.

## Review Notes

- The implementation keeps the selected strategy intact: no venv, no
  dependency management, no server-side Python execution, and packet-2 payloads
  carry `shell_command`, `artifact`, `env={}`, `working_dir=None`, and
  `task_type="python_wheel"`.
- Capability mapping is corrected at the server boundary:
  `python_wheel -> script`; the Redis runner discriminator remains
  `python_wheel`.
- Schedule command overrides for wheel templates are supported through
  type-aware `sanitize_overrides`, not left as a limitation.
- The new `PythonWheelExecutor` mirrors the Scrapy executor transaction/outbox
  shape and creates the existing single `log` stream row.
- The web implementation covers the practical first UI path: upload `.whl`,
  select a wheel artifact, label command as shell command, and use
  `python -m main` as the default wheel command.

## Residual Risks / Follow-up For 2b-2

- The wheel store validates extension + zip integrity and parses wheel metadata
  best-effort, but it does not enforce every PEP 427 structural rule. Bad wheels
  that are valid zips can still fail at agent install time. This is acceptable
  for packet 1 but should be hardened if upload-time validation becomes a user
  pain.
- The agent runner must enforce `--target` + `PYTHONPATH`; packet 1 only encodes
  the contract and verifies the demo wheel supports it.
- `pip install --target` creates no console-script wrappers. Commands must use
  importable module forms such as `python -m main`.
- `/bin/sh` pipeline exit semantics are still a packet-2 runtime concern.

## Verification Run By Codex

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests
# 319 passed

corepack pnpm --filter web test
# 45 passed

corepack pnpm --filter web build
# passed; only existing Rollup annotation/chunk-size warnings

.venv/bin/ruff check apps packages
# All checks passed

git diff --check
# passed
```

Additional offline smoke:

```text
pip install --no-deps --target <tmp-site> tests/fixtures/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl
PYTHONPATH=<tmp-site> DOPILOT_DEMO_URL=http://127.0.0.1:<local-port>/headers python -m main
```

Result: exit 0, printed the local test response headers.
