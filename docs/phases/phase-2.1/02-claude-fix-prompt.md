# Claude Fix Prompt — Phase 2.1 Review Follow-up

You are implementing the follow-up fixes for phase 2.1 in the dopilot repo.

Read first:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/phases/phase-2.1/00-brief.md`
- `docs/phases/phase-2.1/01-claude-implementation-report.md`
- `docs/phases/phase-2.1/02-codex-review.md`
- `.agents/skills/shadcn/SKILL.md`

Do not restart from scratch. Keep the existing Next.js/shadcn implementation and
make only targeted fixes.

## Required fixes

1. Fix the `apps/web` lint script.
   - `corepack pnpm --filter web lint` currently runs deprecated `next lint`,
     prompts interactively, and exits 1.
   - Replace it with a deterministic non-interactive command.
   - A proper ESLint CLI setup is acceptable. If you choose not to add ESLint,
     use another deterministic script and document the choice.

2. Remove React warning noise from web tests.
   - `corepack pnpm --filter web test` currently passes but emits React warnings:
     `Function components cannot be given refs` at `DialogOverlay` and
     `AlertDialogOverlay`.
   - Convert affected shadcn/Radix wrappers to `React.forwardRef` where Radix may
     pass refs through Presence/Portal/Slot/asChild paths.
   - At minimum review/fix:
     - `apps/web/components/ui/button.tsx`
     - `apps/web/components/ui/dialog.tsx`
     - `apps/web/components/ui/alert-dialog.tsx`
     - `apps/web/components/ui/sheet.tsx`
   - Keep shadcn class names and public component APIs stable.

3. Remove the LogViewer `act(...)` warning.
   - Update `apps/web/components/features/__tests__/log-viewer.test.tsx` so mock
     EventSource emits that trigger React state updates are wrapped in `act(...)`.

4. Clean up directly misleading frontend docs.
   - Update the current-stack portions of these docs so they no longer instruct
     future developers to use Vue/Vite/Element Plus paths or deployment:
     - `docs/dopilot/04-gap-i18n.md`
     - `docs/dopilot/05-dev-setup-and-known-issues.md`
     - `docs/dopilot/06-frontend-rewrite.md`
     - `docs/dopilot/07-testing-baseline.md`
     - `docs/dopilot/08-docker-deployment.md`
     - `docs/dopilot/09-package-rename.md`
     - `docs/dopilot/02-gap-scheduling-nodes-push.md`
   - Do not erase useful historical/reference analysis. If a section is old but
     still useful as history, mark it as historical and point to the phase-2.1
     current implementation.

## Verification

Run and report exact results:

```bash
corepack pnpm --filter web lint
corepack pnpm --filter web test
corepack pnpm --filter web build
```

If you change server/static serving code unexpectedly, also run:

```bash
.venv/bin/pytest apps/server/tests/test_web_static.py
```

Write or update:

- `docs/phases/phase-2.1/03-claude-fix-report.md`

The report must include:

- files changed;
- how the lint script was made deterministic;
- whether web test output is free of React ref and `act(...)` warnings;
- exact verification command outcomes;
- any residual risks.
