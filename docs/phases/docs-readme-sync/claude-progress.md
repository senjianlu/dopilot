# Docs README Sync — Claude Progress

Status: **complete**.

## Steps

- [x] Read brief + required context (`AGENTS.md`, `CLAUDE.md`, brief,
      `00-requirements.md`, `10-roadmap.md`, `docs/README.md`, phase-2b brief +
      e2e review, compose/Dockerfile, sidebar, logo).
- [x] Step 1 — moved `logo.svg` → `apps/web/public/logo.svg`; updated the sidebar
      brand icon to render that asset (CSS mask tint; removed unused `Rocket`
      import). App workflows / testids unchanged.
- [x] Step 2 — rewrote `README.md` (English, default entry point) and added
      `README.zh-CN.md` (Simplified Chinese), cross-linked, both showing the logo.
- [x] Step 3 — updated narrow stale spots: `docs/README.md` (frontend now
      Next.js/shadcn/react-i18next, Vue marked historical),
      `docs/dopilot/00-requirements.md` + `docs/dopilot/10-roadmap.md` (script
      phase now `pip --no-deps --target` + `PYTHONPATH`, no venv).
- [x] Step 4 — ran focused checks:
      - `corepack pnpm --filter web test` → 55 passed.
      - `corepack pnpm --filter web build` → static export OK; `out/logo.svg`
        present.
      - `git diff --check` → clean.
      - `rg` sanity check → READMEs clean; remaining docs matches are historical
        context / "无 venv" negations (recorded in the report).
- [x] Step 5 — wrote `01-claude-implementation-report.md`.

## Notes

- Constraints respected: no edits to `reference/scrapydweb/`,
  `docs/architecture/**`, or `docs/phases/**` outside this task dir; no Docker
  long-running crawler claimed as available; only `rabbir/dopilot:latest` named;
  no new web container / nginx / Node runtime introduced.
