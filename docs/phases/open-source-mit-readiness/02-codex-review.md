# Open Source MIT Readiness — Codex Review

## Review result

Accepted after Codex follow-up fixes.

No blocking findings remain in the final diff. The change is docs/repository
metadata only plus deletion of the local `reference/scrapydweb/` snapshot.

## Codex follow-up fixes

- Removed Claude tool-wrapper closing-tag residue from:
  - `LICENSE`
  - `SECURITY.md`
  - `CONTRIBUTING.md`
  - `docs/phases/open-source-mit-readiness/01-claude-implementation-report.md`
  - `docs/phases/open-source-mit-readiness/claude-progress.md`
- Updated current-facing stale wording that remained after Claude's pass:
  - `docs/dopilot/00-requirements.md`: product framing now says self-hosted
    scheduling platform rather than private scheduling platform.
  - `docs/agent-governance/03-commit-convention.md`: `web` scope now describes
    the current Next.js static export SPA.
  - `docs/architecture/00-overview.md`: frontend doc navigation now references
    the current Next.js/shadcn direction.
  - `docs/architecture/01-bootstrap-and-config.md`: introductory product
    framing now says self-hosted scheduling platform.

## Verification

Commands run by Codex:

```bash
test ! -d reference/scrapydweb && test ! -e reference
git diff --check
rg -n "<closing content/invoke tool tags>" LICENSE SECURITY.md CONTRIBUTING.md docs/phases/open-source-mit-readiness
rg -n "reference/scrapydweb|reference/" AGENTS.md CLAUDE.md README.md README.zh-CN.md docs/README.md docs/dopilot docs/agent-governance deploy .github configs apps packages scripts
.venv/bin/ruff check apps packages
.venv/bin/python -m pytest -q
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
```

Results:

- `reference/scrapydweb` and the empty `reference/` directory are absent from the
  working tree.
- `git diff --check` passed.
- Current task files have no Claude tool-wrapper closing-tag residue.
- The required `reference/` sweep still reports intentional lines only:
  "snapshot removed" statements and defensive `.dockerignore` notes. No current
  instruction tells agents to read, edit, import, build, or install a deleted
  local reference tree.
- `ruff check apps packages`: passed.
- `pytest -q`: `433 passed in 12.53s`.
- `corepack pnpm --filter web test`: `55 passed`.
- `corepack pnpm --filter web build`: passed.
- `docker compose config`: passed.

## Residual risks

- Git history still contains the old GPLv3 `reference/scrapydweb/` snapshot until
  the project publishes from a clean repository or performs an explicit history
  rewrite. This was intentionally out of scope for this task and is documented
  in the task brief and `SECURITY.md`.
- Dependency license audit remains a separate public-release follow-up.
