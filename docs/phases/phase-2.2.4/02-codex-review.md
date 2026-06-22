# Phase 2.2.4 — Codex Review

## Scope Reviewed

- Server token helper and runtime wiring.
- `create_app(settings)` dependency injection for generated-token consistency.
- CLI `dopilot-server agent-token print [--quiet]`.
- Server-only and agent-only Docker Compose files.
- Docs and examples for the generated-token deployment flow.
- Claude's reported verification results.

## Findings

### Finding 1 — Medium: first-time generation could race between server startup and CLI

Status: fixed by Codex.

Claude's implementation wrote the generated token atomically, which prevents a
truncated token file, but two processes could still both observe "no token file"
and generate different tokens before the last `os.replace()` won. In practice,
this can happen when a server is starting for the first time while an operator
also runs:

```bash
docker exec <server> dopilot-server agent-token print
```

That could print a token different from the one the server process is already
using in memory.

Codex fixed this by serializing the disk-token read/generate/write path with a
POSIX `fcntl.flock` lock file. Inside the lock the helper re-reads the token
file before generating. The existing atomic temp-file + replace write remains.
On non-POSIX platforms the lock degrades to no lock, while the atomic write
still prevents torn files; the target deployment is Linux containers.

### Finding 2 — Low: one live doc still described missing machine token as off

Status: fixed by Codex.

`docs/dopilot/06-frontend-rewrite.md` still described machine auth as disabled
when `agent_token` is missing. That is true at pure config-load level but
incomplete after phase 2.2.4 because server runtime/CLI can generate and apply a
persisted token. Codex updated the doc to distinguish config loading from the
server runtime behavior.

## Post-Fix Review Result

No unresolved blocking findings.

## Notes

- `load_settings()` remains side-effect-free.
- Configured `DOPILOT_AGENT_TOKEN` still wins and does not touch the generated
  token file.
- Generated token is applied before `create_app(settings)`, and `create_app`
  injects the same settings object into `Depends(get_settings)`.
- `agent-token print` is implemented without DB/Redis/ASGI startup.
- The new agent-only compose file never injects `DOPILOT_ADMIN_API_TOKEN`.
- Existing mentions of old split token names are removal notes or tests asserting
  non-effect, not active config paths.
