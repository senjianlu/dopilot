# Phase 2.2.6 — Acceptance

## Accepted Behavior

- Agent-side `DOPILOT_SERVER_URL` overrides `[agent].server_url`.
- The value is used as the server HTTP base URL for heartbeat and artifact/wheel
  fetch.
- All-in-one compose keeps using the baked `http://server:5000`.
- Agent-only compose requires `DOPILOT_SERVER_URL` and fails fast if it is
  missing.
- Agent-only compose still does not set `DOPILOT_CONFIG` and never injects
  `DOPILOT_ADMIN_API_TOKEN`.

## Verification

- Focused config/heartbeat tests: 25 passed.
- Full agent tests: 121 passed.
- Ruff: passed.
- Agent-only compose with `DOPILOT_SERVER_URL`: passed.
- Agent-only compose without `DOPILOT_SERVER_URL`: failed as expected.
- `git diff --check`: passed.

## Operator Note

For server-on-VM plus K3s-agent deployment, set the agent environment to a URL
reachable from the K3s cluster, for example:

```text
DOPILOT_SERVER_URL=http://<server-vm-ip-or-dns>:5000
```

or a TLS/reverse-proxy URL:

```text
DOPILOT_SERVER_URL=https://dopilot.example.com
```

The server endpoint and Redis endpoint both need to be reachable from the agent
network.
