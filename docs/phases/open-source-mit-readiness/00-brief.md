# Open Source MIT Readiness Brief

## Goal

Prepare the current dopilot tree for an MIT-licensed public release while keeping
the repository documentation accurate for the implemented state through the
Python script stage.

The user has decided:

- dopilot should remain open source;
- the root license should be MIT;
- the local `reference/scrapydweb/` snapshot may be deleted;
- `CLAUDE.md` is stale and must be synchronized with the current repo state.

## Context

Relevant files and decisions:

- `CLAUDE.md`
- `AGENTS.md`
- `README.md`
- `README.zh-CN.md`
- `docs/README.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/05-dev-setup-and-known-issues.md`
- `docs/agent-governance/templates/claude-implementation-prompt.md`
- `deploy/docker/Dockerfile`
- `.dockerignore`

Current important facts:

- dopilot code is implemented under `apps/` and `packages/`.
- The web UI is Next.js static export served by `dopilot-server`.
- Server/agent communication uses Redis Streams plus heartbeat.
- Scrapy `.egg` artifacts and Python `.whl` script artifacts are implemented.
- Docker long-running crawlers remain planned and are out of scope.
- The local GPLv3 `reference/scrapydweb/` snapshot is no longer desired in the
  public MIT tree.

## In Scope

- Add a root `LICENSE` using the standard MIT license text.
- Add minimal public-release docs:
  - `SECURITY.md` with supported-version and vulnerability-reporting guidance;
  - `CONTRIBUTING.md` with concise setup, test, and contribution expectations.
- Delete the tracked `reference/scrapydweb/` tree from the current working tree.
- Update `AGENTS.md` so repository-level agent instructions no longer require a
  deleted local reference tree.
- Update current-facing docs so they no longer claim `reference/scrapydweb/`
  exists locally.
- Preserve the historical architecture docs and completed phase reports as
  historical notes when they describe prior behavior or prior planning.
- Update `CLAUDE.md` so Claude sees the current implementation state, MIT
  release posture, and absence of the local reference snapshot.
- Re-anchor historical `file:line` behavior citations to upstream scrapydweb
  1.6.0 / commit `1341cf9` instead of the deleted local tree.
- Update governance templates that still forbid editing `reference/scrapydweb/`
  so future Claude prompts forbid fetching/copying upstream code instead.
- Keep README default English, with Chinese cross-link, and state MIT license.

## Out Of Scope

- No behavior changes to server, agent, web, migrations, executors, or runtime
  configuration.
- No Docker image publishing change.
- No dependency upgrade or broad license audit in this task.
- No git history rewrite in this task. Deleting `reference/scrapydweb/` removes
  it from the current tree only. A future clean public repository or history
  rewrite is still required if the existing git history must be free of the old
  GPL snapshot.
- No updates to completed phase reports that would alter historical facts.

## Required Implementation Order

1. Ask Claude for read-only feasibility validation of this scope.
2. Resolve any blocking feedback into this brief.
3. Apply documentation/license/security/contributing updates.
4. Delete `reference/scrapydweb/`.
5. Search for stale current-facing `reference/scrapydweb/` claims and fix the
   ones that would mislead new contributors.
6. Run focused checks and review the diff.

## Acceptance Criteria

- `LICENSE` exists at the repository root and uses SPDX identifier `MIT`.
- `README.md` and `README.zh-CN.md` link to the license and no longer describe
  dopilot as a private product or claim a local `reference/scrapydweb/` snapshot
  is present.
- `SECURITY.md` exists and warns operators to replace default/example secrets
  before exposure.
- `CONTRIBUTING.md` exists and lists the narrow local verification commands.
- `CLAUDE.md` reflects:
  - current implemented state through Python wheel script support;
  - no local `reference/scrapydweb/` directory;
  - upstream scrapydweb may be consulted only externally as behavior context,
    never copied or vendored.
- `reference/scrapydweb/` is absent from the working tree.
- Current-facing docs/templates do not instruct agents to read, edit, import, or
  build the deleted local reference tree.
- Historical docs may still mention `reference/scrapydweb/` when clearly part of
  old phase history or behavior-reference notes.

## Required Checks

```bash
rg -n "reference/scrapydweb|reference/" AGENTS.md CLAUDE.md README.md README.zh-CN.md docs/README.md docs/dopilot docs/agent-governance deploy .github configs apps packages scripts
git diff --check
```

If time permits, also run:

```bash
pytest
ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

## Risks To Watch

- Deleting the local reference snapshot can break stale docs, prompts, or scripts
  that still assume the directory exists.
- The old snapshot remains in git history unless a future history rewrite or
  clean public repository is created.
- A root MIT license does not automatically audit third-party dependency
  licenses; dependency license review remains a public-release follow-up.
- Placeholder `change-me` credentials are acceptable for examples only if docs
  clearly warn they are not production-safe.
