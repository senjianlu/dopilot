# Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/open-source-mit-readiness/00-brief.md`

The user explicitly approved deleting the local reference snapshot and wants the
repository to be open source under MIT.

## Required Context

Read these before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `README.zh-CN.md`
- `docs/phases/open-source-mit-readiness/00-brief.md`
- `docs/phases/open-source-mit-readiness/00a-feasibility-review.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/05-dev-setup-and-known-issues.md`
- `docs/agent-governance/templates/claude-implementation-prompt.md`

Use `rg` to locate stale current-facing references to `reference/scrapydweb/` or
`reference/`.

## Constraints

- Keep changes scoped to docs, repository metadata, and deleting the local
  reference snapshot.
- Do not change runtime behavior in `apps/`, `packages/`, migrations, or deploy
  logic except stale comments if needed.
- Do not rewrite completed phase reports to hide historical facts.
- Do not fetch, vendor, copy, or import upstream scrapydweb code.
- Do not inspect the contents of `reference/scrapydweb/`; delete the tree.
- Root license must be MIT and should include `SPDX-License-Identifier: MIT`.
- `CLAUDE.md` must be synchronized to the current implementation state:
  Next.js static export, Redis Streams communication, Scrapy + Python wheel
  support implemented, Docker crawler support still planned, no local
  `reference/scrapydweb/`.
- Re-anchor historical architecture `file:line` references to upstream
  scrapydweb 1.6.0 / commit `1341cf9` rather than a local tree.

## Output Required

Create or update:

- `docs/phases/open-source-mit-readiness/01-claude-implementation-report.md`
- `docs/phases/open-source-mit-readiness/claude-progress.md`

The report must include:

- changed files grouped by area;
- implementation notes;
- commands run with pass/fail output;
- known risks or incomplete items.

## Required Checks

Run these after edits:

```bash
test ! -d reference/scrapydweb
rg -n "reference/scrapydweb|reference/" AGENTS.md CLAUDE.md README.md README.zh-CN.md docs/README.md docs/dopilot docs/agent-governance deploy .github configs apps packages scripts
git diff --check
```

The `rg` command may still find historical phase files or behavior-reference
notes. In the report, distinguish acceptable historical residue from stale
current-facing instructions.

If a command fails because of Claude permissions, record the failed command and
continue with the rest of the task.
