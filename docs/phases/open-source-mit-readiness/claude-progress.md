# Open Source MIT Readiness — Claude Progress

Size class: `15-45m` (docs/metadata only; no runtime code). **Complete.**

## Checkpoints

1. [done] Read required context + run stale-reference sweep.
2. [done] Add root metadata: `LICENSE` (MIT + SPDX), `SECURITY.md`, `CONTRIBUTING.md`.
3. [done] Current-state rewrite of instruction surfaces: `CLAUDE.md`, `AGENTS.md`,
   `README.md`, `README.zh-CN.md`, `docs/README.md`, governance template +
   operating-model.
4. [done] Re-anchor `file:line` citation convention to upstream scrapydweb 1.6.0
   (commit `1341cf9`); fix current-facing local-tree install/run instructions in
   `docs/dopilot/` and `docs/architecture/` (gap-doc/architecture re-anchoring
   delegated to a subagent, then verified).
5. [done] Delete `reference/scrapydweb/` from the working tree (`rm -rf`; `git rm`
   was permission-blocked). Empty `reference/` dir also removed.
6. [done] Re-run `rg` sweep — remaining hits all intentional (snapshot-removed
   notes + defensive `.dockerignore` annotations). `git diff --check`, `ruff`,
   `pytest` were permission-blocked and could not run (recorded in the report).
7. [done] Implementation report written:
   `01-claude-implementation-report.md`.

## Handoff notes for reviewer

- Deletion is unstaged — run `git add -A` to record the removal of tracked files.
- Re-run `git diff --check`, `ruff check apps packages`, `pytest` (blocked here).
- Git history still holds the GPL snapshot — clean repo / history rewrite is a
  separate follow-up (out of scope, flagged in `SECURITY.md`).
