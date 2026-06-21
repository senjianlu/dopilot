# Docs README Sync — Claude Implementation Report

Brief: `docs/phases/docs-readme-sync/00-brief.md`

## Summary

Synced the public README and top-level docs navigation with the current dopilot
state (through the Python wheel script phase), and adopted the committed logo as
the canonical web asset + sidebar brand mark. All changes are scoped to the
brief. No historical phase files (`docs/phases/**` outside this task dir) and no
`docs/architecture/**` files were touched. No product behavior changed except the
cosmetic logo usage.

## Changed Files By Area

### Logo / web asset (cosmetic behavior)

- `apps/web/public/logo.svg` — **new**; the submitted `logo.svg` moved from the
  repo root into the canonical Next.js public asset location. The root copy is
  gone (it was an untracked file, so this is a plain move, not a tracked rename).
- `apps/web/components/layout/app-sidebar.tsx` — replaced the placeholder
  `Rocket` lucide icon in the sidebar brand header with the public `/logo.svg`
  asset. Removed the now-unused `Rocket` import. Navigation items, testids, and
  workflows are unchanged.

### Public README

- `README.md` — **rewritten** as the concise, default English entry point.
  Displays the logo, links to `README.zh-CN.md`, explains how dopilot works
  (server/agent roles, one unified image, Redis Streams + heartbeat, PostgreSQL +
  `/server-data/logs`), states current support (Scrapy + Python wheel available;
  Docker long-running crawlers planned), documents the Python wheel execution
  model (`pip install --no-deps --target` + `PYTHONPATH`, no venv), and gives
  quick deploy (`make compose-up`, base-image note, `http://localhost:5000`) and
  local development (PostgreSQL + Redis; Next.js dev; no Vite/5173) sections.
- `README.zh-CN.md` — **new**; Simplified Chinese counterpart mirroring the
  English README and linking back to `README.md`.

### Docs navigation / quick facts

- `docs/README.md` — updated the three spots that still presented the old
  frontend as current: the i18n nav row (`vue-i18n` → `react-i18next`, marked
  "阶段 2.1 起，原 vue-i18n"), the frontend-rewrite nav row, and the 决策速查
  frontend bullet (now Next.js static export + shadcn/ui + Recharts, with the
  Vue/Element Plus selection marked as superseded).
- `docs/dopilot/00-requirements.md` — updated decision #16 and the 阶段 2 roadmap
  row to describe the actual phase-2b script model (`pip install --no-deps
  --target` + `PYTHONPATH`, explicitly **no venv / no dependency resolution / no
  console-script**), pointing at `docs/phases/phase-2b/00-brief.md`.
- `docs/dopilot/10-roadmap.md` — updated the 阶段2 ASCII lane and the
  `PythonWheelExecutor` epic row to the same no-venv model.

### Task artifacts

- `docs/phases/docs-readme-sync/01-claude-implementation-report.md` — this report.
- `docs/phases/docs-readme-sync/claude-progress.md` — progress log.

## Implementation Notes

- **Logo rendering in the sidebar.** The committed `logo.svg` is a `currentColor`
  monochrome SVG. A plain `<img>` would paint it black regardless of theme (low
  contrast inside the dark `bg-sidebar-primary` brand box). To render the public
  asset while keeping it legible in both light and dark sidebars, it is applied
  as a CSS `mask-image: url(/logo.svg)` on a `bg-current` span so it inherits the
  `text-sidebar-primary-foreground` tint. The asset itself is used (not an inline
  re-draw), so it stays a single source of truth with the README.
- **README image path.** Both README files reference `apps/web/public/logo.svg`
  (relative to the repo root), which renders on GitHub and points at the same
  asset the app serves at `/logo.svg`.
- **Quick deploy.** Uses `make compose-up`, which builds the two local base
  images (`rabbir/dopilot-py-base:local`, `rabbir/dopilot-web-base:local`) via
  the `docker-base` target before bringing up the stack; the base-image
  requirement is called out explicitly. Only `rabbir/dopilot:latest` is named as
  the runtime image — no `rabbir/dopilot-agent` or `senjianlu` namespaces.
- **Scope discipline.** Only the narrow stale spots were edited. Decision #6 in
  `00-requirements.md` (which already correctly states Next.js as current and Vue
  as superseded) and the already-correct Next.js/react-i18next nav rows in
  `10-roadmap.md` were left as-is. No Docker/K3s long-running crawler is described
  as available anywhere.

## Tests Run

| Command | Result |
| --- | --- |
| `corepack pnpm --filter web test` | **PASS** — 12 files, 55 tests passed |
| `corepack pnpm --filter web build` | **PASS** — static export built (13 routes); `apps/web/out/logo.svg` present in the export |
| `git diff --check` | **PASS** — clean (no whitespace errors / conflict markers) |

### `rg` sanity check (historical-context note)

```bash
rg -n "Vue 3 \+ Element Plus|Vite|vue-i18n|venv" \
  README.md README.zh-CN.md docs/README.md \
  docs/dopilot/00-requirements.md docs/dopilot/10-roadmap.md
```

- `README.md`, `README.zh-CN.md` — **no matches** (clean; neither presents the
  old stack).
- The remaining matches in `docs/README.md`, `docs/dopilot/00-requirements.md`,
  and `docs/dopilot/10-roadmap.md` are **historical context or explicit
  negations**, not current-plan statements:
  - frontend mentions are tagged "阶段 2.1 起，原 vue-i18n" / "替换原 Vue 3 +
    Element Plus 选型" (i.e. the superseded selection);
  - every `venv` hit is now a negation — "无 venv" / "不创建 venv".
- This matches the brief's note: the searched terms remain only as historical
  context. The acceptance condition ("no longer state … as the current plan") is
  satisfied.

Frontend test/build commands ran successfully on this host; no blockers.

## Known Risks / Incomplete Items

- **Logo dark-mode contrast (README).** The brief flagged that the
  `currentColor` logo can be low-contrast if rendered as an external image in
  README dark mode. On GitHub the README logo renders with the document's default
  foreground color; in dark themes the mark may appear light/medium contrast. It
  is left as the committed asset per scope (no recolor / no separate dark
  variant). In the app this is fully mitigated by the mask-tint approach above.
- **Docs `rg` matches remain (by design).** As recorded above, the historical /
  negated occurrences are intentional and were not scrubbed, to avoid rewriting
  phase history or decision context.
- **License section.** Both READMEs defer to the repository for license details
  (no `LICENSE` file content was assumed). No new licensing claim was introduced.
- No backend (`pytest`) or `ruff` runs were required by this brief; this change
  set is docs + one cosmetic web component edit, covered by the web test/build.
