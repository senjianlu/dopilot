# Docs README Sync — Codex Review

Status: accepted after Codex follow-up edits.

## Review Result

Claude completed the scoped README/docs sync and logo adoption. Codex reviewed
the diff against `docs/phases/docs-readme-sync/00-brief.md` and found two
README accuracy issues:

- The local development section implied Next.js dev proxied `/api` to the
  server. The current Next config has no rewrite/proxy; the client uses
  `NEXT_PUBLIC_API_BASE` when pointing dev mode at a separately running server.
- The README used `specified` as the node strategy label. The current
  public/web vocabulary is `selected`, `all`, and `random`; `specified` is only
  an internal seam enum alias.

Codex fixed both issues in `README.md` and `README.zh-CN.md`. While reviewing the
local-dev instructions, Codex also made the Redis prerequisite executable for
host-run server/agent processes: the committed compose Redis service is not
published to the host, so the README now starts a host-published Redis container
and tells the operator to use a local agent config with
`server_url = "http://localhost:5000"`, `advertise_endpoint = "localhost:6800"`,
and `redis.url = "redis://localhost:6379/0"`.

No blocking findings remain.

## Files Reviewed

- `README.md`
- `README.zh-CN.md`
- `apps/web/components/layout/app-sidebar.tsx`
- `apps/web/public/logo.svg`
- `docs/README.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/docs-readme-sync/01-claude-implementation-report.md`

## Verification

Codex ran:

```text
corepack pnpm --filter web test -> 12 files / 55 tests passed
corepack pnpm --filter web build -> passed; apps/web/out/logo.svg present
git diff --check -> passed
```

Codex also ran a sanity search over both README files plus the narrow docs files:

```text
rg -n "Vue 3 \+ Element Plus|Vite|vue-i18n|venv|dopilot-agent:latest|rabbir/dopilot-agent|localhost:5173|Dockerfile\.server|Dockerfile\.agent|proxying /api|specified" README.md README.zh-CN.md docs/README.md docs/dopilot/00-requirements.md docs/dopilot/10-roadmap.md
```

Remaining matches are only:

- historical-context mentions of the superseded frontend stack;
- `vue-i18n` as old wording;
- explicit `no venv` statements for Python wheel execution; or
- `.venv/bin/activate` in the local development setup, which is the developer
  Python environment and not the Python wheel runtime model.

There are no README matches for the removed old deployment facts, stale
local-dev proxy wording, or `specified` node-strategy wording.

Codex checked that no `docs/phases/**` files outside
`docs/phases/docs-readme-sync/` were modified.

## Residual Notes

- The README logo uses the submitted `currentColor` SVG. App sidebar contrast is
  handled with a CSS mask tint; GitHub README rendering may vary by theme.
- This task did not run backend pytest or ruff because the code change is a
  cosmetic web asset/sidebar update plus docs.
