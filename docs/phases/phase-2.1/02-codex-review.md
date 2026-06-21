# Phase 2.1 — Codex Review

## Review status

Claude completed the main migration and the core behavior is working:

- Next static export builds successfully.
- FastAPI serves exported route files and does not rewrite `/api/*`.
- Host backend tests, web tests, build, ruff, compose config, and Docker browser smoke have passed.

Codex found follow-up issues that should be fixed before phase acceptance.

## Findings

### 1. `apps/web` lint script is non-deterministic and fails interactively

Running `corepack pnpm --filter web lint` executes `next lint`. With Next 15 this
enters the deprecated interactive ESLint setup prompt and exits with status 1.
This is not part of the current acceptance command list, but leaving a broken
script in `package.json` will mislead future CI or local development.

Expected fix:

- Replace `next lint` with a non-interactive command.
- Either configure ESLint CLI properly, or remove/replace the script with a
  deterministic project command. Do not leave an interactive prompt.

### 2. Web tests pass with React warnings from Radix/shadcn wrappers

`corepack pnpm --filter web test` passes, but stderr contains repeated React 18
warnings:

- `Function components cannot be given refs` at `DialogOverlay`.
- `Function components cannot be given refs` at `AlertDialogOverlay`.

The warnings appear when Radix Presence/Portal/Slot paths attach refs to local
wrapper components. This can reduce confidence in focus management and makes
test output noisy.

Expected fix:

- Convert the affected shadcn/Radix wrappers to `React.forwardRef` where refs may
  be passed by Radix or `asChild`.
- At minimum cover `DialogOverlay`, `DialogContent`, `AlertDialogOverlay`,
  `AlertDialogContent`, and the shared `Button` component if it is used under
  Radix `asChild`.
- Re-run `corepack pnpm --filter web test` and confirm the ref warnings are gone.

### 3. LogViewer tests pass with missing `act(...)` warnings

`components/features/__tests__/log-viewer.test.tsx` emits React warnings because
the mock EventSource emits state-changing events outside `act(...)`.

Expected fix:

- Wrap mock SSE emits that update React state in `act(...)`.
- Re-run `corepack pnpm --filter web test` and confirm the `act(...)` warnings are gone.

### 4. Several directly relevant docs still describe the old Vue/Vite frontend

Claude updated the phase brief, requirements, roadmap, and the top of
`06-frontend-rewrite.md`, but several user-facing docs still describe the old
Vue/Vite/Element Plus implementation in sections that affect future work:

- `docs/dopilot/04-gap-i18n.md`
- `docs/dopilot/05-dev-setup-and-known-issues.md`
- `docs/dopilot/06-frontend-rewrite.md`
- `docs/dopilot/07-testing-baseline.md`
- `docs/dopilot/08-docker-deployment.md`
- `docs/dopilot/09-package-rename.md`
- `docs/dopilot/02-gap-scheduling-nodes-push.md`

Expected fix:

- Update the sections that would mislead a developer about current frontend
  paths, dev server, deployment, i18n framework, and static asset strategy.
- Do not attempt a full rewrite of historical analysis; add clear phase-2.1
  authority notes where old references are intentionally retained as historical
  context.

## Already verified by Codex

- `corepack pnpm --filter web build` passed.
- `corepack pnpm --filter web test` passed, with the warnings listed above.
- `scripts/smoke-phase1-ui.sh` passed against Docker and browser flows before
  this review; the smoke covered login/navigation, nodes, artifact upload,
  Scrapy template run/logs, built-in wheel run/logs, Python wheel template
  run/logs, task detail, schedules, and node lifecycle actions.
