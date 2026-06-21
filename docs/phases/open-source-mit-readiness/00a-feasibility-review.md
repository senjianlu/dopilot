# Open Source MIT Readiness — Claude Feasibility Review

Read-only validation of `00-brief.md`. No code changed, no files deleted.

## 1. Verdict

**Feasible with changes.** The scope (add MIT `LICENSE`, `SECURITY.md`,
`CONTRIBUTING.md`; delete the local `reference/scrapydweb/` tree; resync
current-facing docs; no runtime/history change) is achievable as a docs-only
task. There are no hard blockers, but two current-facing instruction surfaces
and one citation convention need explicit handling before the work lands, and
`CLAUDE.md` is more stale than the brief implies.

## 2. Blocking issues

None. Nothing in scope requires a runtime or behavioral change, and every target
file exists.

## 3. Risky assumptions

- **`CLAUDE.md` is stale beyond the reference snapshot.** The brief frames the
  `CLAUDE.md` update around "reference snapshot + Python wheel state," but the
  file also makes claims that are now wrong and must be fixed in the same pass,
  or the resync is half-done:
  - **Frontend stack:** `CLAUDE.md:40` says the frontend is "Vue 3 + Element
    Plus + Vite + TypeScript." Reality (confirmed in `apps/web/package.json`,
    `README.md`, `docs/dopilot/05-dev-setup-and-known-issues.md` §0/§9) is
    **Next.js static export + shadcn/ui + react-i18next**. This is the single
    most misleading stale claim for a new contributor.
  - **Build state:** `CLAUDE.md:73` says "dopilot's own build/test/lint pipeline
    doesn't exist yet — phase 0 scaffolds the dopilot skeleton." Phases 0/1/2a/2b
    are complete; tests, Dockerfiles, CI, and wheel execution all exist.
  - **Product framing:** `CLAUDE.md:15` calls dopilot "a private scheduling
    platform" — conflicts with the MIT/open-source posture the brief wants.
- **`file:line` citation convention points into the deleted tree.** `CLAUDE.md:31`
  declares all `file:line` citations are "relative to `reference/scrapydweb/`",
  and `docs/architecture/*` use them heavily (e.g. `vars.py:29`). Once the local
  tree is gone, these resolve to nothing locally. The brief says preserve
  historical architecture docs unchanged, but the *convention statement itself*
  is current-facing guidance and will mislead. Needs re-anchoring (see §4),
  not deletion of the architecture docs.
- **Heavy verification commands for a docs-only change.** The brief's Required
  Checks include `corepack pnpm --filter web test` and `... build`. These are
  unnecessary for a license/docs change, and this environment lacks a ready
  pnpm/web toolchain (per project setup notes), so they are likely to fail for
  environmental reasons unrelated to the change. See §5.

## 4. Missing decisions / questions for Codex

1. **Citation re-anchor wording.** When the local snapshot is gone, what should
   `CLAUDE.md`'s convention line and the architecture docs say `file:line` is
   relative to? Recommended: "relative to upstream scrapydweb 1.6.0, commit
   `1341cf9`" (already recorded in `05-dev-setup-and-known-issues.md` §1). This
   keeps historical citations meaningful without re-introducing the tree.
2. **Is `AGENTS.md` in the edit set?** It is listed under the brief's Context but
   not its In-Scope edits, yet `AGENTS.md:30-31` and `AGENTS.md:72` are
   current-facing instructions telling agents to *use the local
   `reference/scrapydweb/`* as reference/oracle. After deletion these are stale.
   The brief's own acceptance criterion ("current-facing docs/templates do not
   instruct agents to read/edit/import/build the deleted local reference tree")
   requires editing `AGENTS.md`. Please add it explicitly to In Scope.
3. **Test-oracle story after deletion.** `CLAUDE.md` and `AGENTS.md` both call
   `reference/scrapydweb/` a "test oracle." No dopilot test imports it (it was
   manual/behavioral), but Codex should confirm the reword is "consult upstream
   externally as behavior context," not "the local oracle still exists."
4. **Tagline wording.** `README.md:8` ("A private, single-admin scheduling
   platform"). Keep "single-admin" (accurate); decide whether "private" stays
   (reads as "private product," which the brief wants gone) — recommend
   "self-hosted, single-admin."

## 5. Suggested scope cuts / sequencing

- **Cut the web `test`/`build` checks** from the acceptance gate for this task;
  it changes no web code. Keep `git diff --check` and the `rg` stale-reference
  sweep as the real gates; run `pytest`/`ruff` only opportunistically. The `rg`
  check in the brief should be run *after* the edits and is the meaningful
  signal here.
- **Sequence: edit docs before deleting the tree.** Do all current-facing
  rewrites (`CLAUDE.md`, `AGENTS.md`, `README*`, `docs/README.md`, the prompt
  template) first, then delete `reference/scrapydweb/`, then re-run the `rg`
  sweep so any remaining current-facing claim is caught against an actually-empty
  tree.
- **Low-priority residue (optional this task):** `.dockerignore:3`,
  `pyproject.toml:32`, and `deploy/docker/Dockerfile:13` exclude `reference/`.
  After deletion these are harmless no-ops; leaving them is fine, but a one-line
  comment update avoids future confusion. Not a blocker.
- **Record the residual license risk, don't try to fix it here.** The brief
  already (correctly) keeps git history out of scope: the GPLv3 scrapydweb
  snapshot remains in history even after the working-tree delete, while root
  `LICENSE` will say MIT. That is acceptable for this task as long as
  `SECURITY.md`/release notes or a follow-up brief flag that a clean public repo
  or history rewrite is the real remediation. This is a sequencing note, not a
  blocker for the doc/license work.

## Summary

No blockers. Proceed, but (a) treat the `CLAUDE.md` resync as a full
current-state pass — fix the Next.js frontend, completed-build, and "private"
claims, not just the reference snapshot; (b) add `AGENTS.md` to the in-scope
edits; (c) decide the `file:line` re-anchor so architecture-doc citations stay
meaningful; and (d) drop the web build/test from the acceptance gate for a
docs-only change.
