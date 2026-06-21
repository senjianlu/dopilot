# Phase 2.1 — Claude Fix Report (Codex review follow-up)

Targeted fixes for the four findings in `02-codex-review.md`. The existing
Next.js + shadcn/ui implementation was kept; nothing was rebuilt.

## 1. Deterministic, non-interactive `apps/web` lint

**Problem.** `lint` ran `next lint`, which under Next 15 drops into the
deprecated interactive ESLint setup prompt and exits 1.

**Fix.** Replaced it with a real ESLint CLI flat-config setup:

- `apps/web/package.json`: `"lint": "eslint ."` (was `"next lint"`).
- New `apps/web/eslint.config.mjs` (flat config): `@eslint/js` recommended +
  `typescript-eslint` recommended + `eslint-plugin-react-hooks`
  (`recommended-latest`), with `_`-prefixed args/vars allowed in
  `@typescript-eslint/no-unused-vars`, and `out/`, `.next/`, `next-env.d.ts`,
  Playwright artifacts ignored.
- devDeps added to `apps/web/package.json`: `eslint@^9`, `@eslint/js@^9`,
  `typescript-eslint@^8`, `eslint-plugin-react-hooks@^5`, `globals` (+
  `pnpm-lock.yaml` updated).

**Why not `eslint-config-next`.** `eslint-config-next@latest` (v16) pulls
`eslint-plugin-react@7.37.5`, which throws under the current ESLint 10 line
(`contextOrFilename.getFilename is not a function`). Pinning to a lean, stable
ESLint 9 + typescript-eslint stack is version-safe and only needs the core JS +
TypeScript + React-hooks correctness rules this repo cares about. The
`react-hooks/exhaustive-deps` rule it enables also validates the existing inline
`// eslint-disable-next-line react-hooks/exhaustive-deps` comments in
`tasks/page.tsx` and `templates/page.tsx` (previously dangling references).

`eslint .` runs non-interactively and exits 0 on clean code, non-zero on errors.

Two real findings surfaced by the new lint were fixed (not suppressed):

- `lib/api/__tests__/client.test.ts`: unused adapter arg `config` → `_config`.
- `e2e/helpers/ui.ts`: removed 3 now-unused
  `// eslint-disable-next-line no-constant-condition` directives (ESLint 9's
  default `no-constant-condition` no longer flags `while (true)`). The loops are
  unchanged.

`pnpm-workspace.yaml`: replaced leftover `allowBuilds` placeholders that broke
`pnpm install`'s build-script gate. Dropped `vue-demi` (Vue is gone) and kept
only the build-script packages present in this stack (`esbuild`,
`@tailwindcss/oxide`, `sharp`) so fresh installs run non-interactively.

## 2. React ref warnings removed (forwardRef)

**Problem.** The shadcn primitives shipped as plain function components
(React-19 ref-as-prop style), but this repo runs React 18.3.1. When Radix's
`*Portal` wraps its overlay child in `Presence` → `Portal` → `Slot` and forwards
a ref, React 18 logs *"Function components cannot be given refs"* at
`DialogOverlay` and `AlertDialogOverlay`.

**Fix.** Converted the affected wrappers to `React.forwardRef`, forwarding the
ref to the underlying Radix primitive. Class names, `data-slot`/`data-size`
attributes, extra props (`showCloseButton`, `size`, `side`), and the exported
public APIs are unchanged.

- `components/ui/button.tsx`: `Button` (used as an `asChild` child of Radix
  triggers, so it can receive a Slot-forwarded ref).
- `components/ui/dialog.tsx`: `DialogOverlay`, `DialogContent`.
- `components/ui/alert-dialog.tsx`: `AlertDialogOverlay`, `AlertDialogContent`.
- `components/ui/sheet.tsx`: `SheetOverlay`, `SheetContent`.

The actual warnings came from the `*Overlay` components (Portal children);
`*Content` and `Button` were converted as the review requested for robustness
against `asChild`/Slot ref paths.

## 3. LogViewer `act(...)` warning removed

`components/features/__tests__/log-viewer.test.tsx`: the mock `EventSource`
emits (`log`, `complete`) call `setState` in the component's handlers, so they
must run inside `act(...)`. Wrapped them in `act(() => { ... })` (imported from
`@testing-library/react`). No assertion logic changed.

## 4. Frontend docs no longer instruct the old Vue/Vite/Element Plus stack

Each doc got a phase-2.1 historical banner near the top (authoritative current
stack = Next.js static export + shadcn/ui + Recharts + react-i18next; pointing to
`06-frontend-rewrite.md`'s decision table and
`docs/phases/phase-2.1/01-claude-implementation-report.md`), plus surgical inline
historical notes on the directly-misleading current-tense guidance (frontend
paths, dev server, deployment/static-asset strategy, i18n framework, test
framework/selectors). Substantive analysis and scrapydweb `file:line` behavioral
references were preserved, not erased.

- `04-gap-i18n.md` — banner + vue-i18n→react-i18next notes (catalogs now
  `apps/web/lib/i18n/locales/{zh,en}.ts`, `{{var}}` interpolation; Element Plus
  locale → shadcn/ui has none); old tables relabeled "（旧设计）".
- `05-dev-setup-and-known-issues.md` — banner + the §1 authoritative layout's
  `apps/web/` subtree rewritten to the Next.js structure (`app/`, `components/`,
  `lib/`, `next.config.mjs`, `components.json`, `eslint.config.mjs`, `out/`), old
  Vue tree retained as a "已移除" historical note; `next dev` / static-export
  deployment notes. Non-web layout entries and backend/agent pitfalls untouched.
- `06-frontend-rewrite.md` — top banner + decision table were already correct;
  added historical markers to the §1 ASCII diagram, the prose, the M0 row, the
  directory tree, and the dev-server/deployment bullets.
- `07-testing-baseline.md` — banner + Vue Test Utils → vitest +
  @testing-library/react notes; Element Plus class selectors → `data-tone` /
  `data-testid`; CI step → `eslint .` + static-export build. scrapydweb-oracle
  framing preserved.
- `08-docker-deployment.md` — banner + Vite build output → Next.js static export
  (`apps/web/out` → `/app/web`), same-origin hosting, no `next start` / Node
  runtime / independent web container, no Vite dev proxy. Backend/compose/Redis
  and the `reference/` build-context exclusion untouched.
- `09-package-rename.md` — banner + Vue/Vite fingerprint/stack notes; "porting
  notes, not a rename plan" framing kept.
- `02-gap-scheduling-nodes-push.md` — banner + a few `apps/web/src` / Element
  Plus current-tense pointers neutralized; scheduling/nodes/push analysis kept.

## Verification — exact outcomes

| Command | Result |
| --- | --- |
| `corepack pnpm --filter web lint` | **exit 0** — runs `eslint .` non-interactively, no errors/warnings |
| `corepack pnpm --filter web test` | **43 passed (10 files), exit 0** — 0 React ref/`act(...)`/other warnings in output |
| `corepack pnpm --filter web build` | **exit 0** — 13 routes exported to `out/` (incl. `_not-found`, `/tasks/detail`) |
| `corepack pnpm --filter web typecheck` (`tsc --noEmit`) | **exit 0** (ran because forwardRef changed component types) |
| `corepack pnpm install --filter web --frozen-lockfile` | **exit 0** — "Already up to date" (lockfile/Docker parity holds after dep adds) |
| `.venv/bin/pytest apps/server/tests/test_web_static.py` | **4 passed** (server static-serving code unchanged; run as a safety check) |

Web test output is confirmed free of both the `Function components cannot be
given refs` ref warnings and the LogViewer `act(...)` warning (grep for
`warning` over the full test stderr returns 0).

## Residual risks / notes

- **ESLint scope is intentionally lean.** No `eslint-config-next` (broken on the
  current ESLint 10 line) and no `eslint-plugin-react`/`jsx-a11y`. The config
  enforces core JS, TypeScript correctness, and React Hooks rules — not Next.js
  core-web-vitals or a11y. Adding those later requires either pinning ESLint to a
  version compatible with `eslint-plugin-react`, or waiting for upstream fixes.
- **Web base image / lockfile.** The new ESLint devDeps land in `pnpm-lock.yaml`,
  so the `web-deps` base image (`pnpm install --filter web --frozen-lockfile`)
  should be rebuilt; the final runtime image only copies `apps/web/out`, so its
  size is unaffected. `--frozen-lockfile` verified locally.
- **forwardRef vs. shadcn upstream.** These components now diverge from the
  React-19-style shadcn registry source (function components). A future
  `shadcn add --overwrite` would reintroduce the warnings under React 18; the
  forwardRef change must be re-applied if components are regenerated, or React
  upgraded to 19.
- Docker browser smoke (`scripts/smoke-phase1-ui.sh`) was **not** re-run for this
  follow-up — the changes are lint config, test-only `act(...)`, ref-forwarding
  (no DOM/behavior change), and docs. The phase-2.1 smoke recorded in
  `02-codex-review.md` already covered the live flows.
