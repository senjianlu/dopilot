# 03 — Git commit convention

This repository follows **[Conventional Commits 1.0.0](https://www.conventionalcommits.org/)**,
adapted to dopilot's domain. Every commit on every branch must conform. The rule
is enforced locally by a dependency-free `commit-msg` hook (see §7), so a
malformed message is rejected before it lands.

## 1. Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

- The **header** (`<type>(<scope>): <subject>`) is the only required line.
- A blank line separates header / body / footer.

## 2. Subject rules

- **Imperative mood**, present tense: "add", not "added" / "adds".
- **Lowercase** first word, **no trailing period**.
- **<= 72 characters** (aim for <= 50). The header is what shows up in
  `git log --oneline`, changelogs, and GitHub lists — keep it scannable.
- Describe *what changes*, not "phase X" alone — encode the phase as a suffix
  `(phase 1.7.1)` or a `Phase:` footer when useful, but the subject should still
  read on its own.

## 3. Types

| type       | use for                                                        |
|------------|----------------------------------------------------------------|
| `feat`     | a new capability / user-visible behavior                       |
| `fix`      | a bug fix                                                       |
| `docs`     | documentation only (incl. `docs/`, `CLAUDE.md`, READMEs)       |
| `refactor` | code change that neither fixes a bug nor adds a feature         |
| `perf`     | performance improvement                                        |
| `test`     | adding or correcting tests only                                |
| `build`    | build system, Dockerfiles, dependency or packaging changes     |
| `ci`       | CI configuration and workflows (`.github/`)                    |
| `chore`    | tooling / meta with no src, test, or docs behavior change       |
| `style`    | formatting only (whitespace, lint) — no logic change           |
| `revert`   | reverts a previous commit (body: `Reverts: <hash>`)            |

## 4. Scopes (optional but encouraged)

dopilot is a monorepo; the scope names the area touched:

| scope      | area                                                           |
|------------|----------------------------------------------------------------|
| `server`   | `apps/server` (FastAPI hub, scheduler, executors, migrations)  |
| `agent`    | `apps/agent` (worker executor)                                 |
| `web`      | `apps/web` (Next.js static export SPA)                          |
| `protocol` | `packages/protocol` (shared server<->agent schemas)            |
| `deploy`   | `deploy/docker`, compose, image build/publish                  |
| `ci`       | CI workflows                                                   |
| `configs`  | `configs/`                                                     |
| `docs`     | docs tree (as a *scope* paired with a non-`docs` type)         |
| `repo`     | root tooling / meta (Makefile, pyproject, pnpm workspace)      |

Omit the scope when a change is genuinely cross-cutting (e.g. a repo-wide
scaffold). Use **one** scope; a change spanning many areas usually wants to be
split, or left scope-less.

## 5. Footers

- `Co-Authored-By: <name> <email>` — keep when pairing with an agent.
- `Refs: docs/dopilot/00-requirements.md` — point at the authoritative decision.
- `Phase: 1.7.1` — optional, for the phased roadmap.
- `BREAKING CHANGE: <description>` — or a `!` after the type/scope
  (`feat(protocol)!: ...`) for an incompatible change.

## 6. Examples

```
feat(server): add healthy-only node selection for scrapy dispatch
fix(ci): keep Docker image tags within their build job
docs: align v1 architecture (greenfield/FastAPI/PostgreSQL)
refactor: clean-cut id naming across server and agent (phase 2a)
build(deploy): unify docker image and serve web UI from one container
```

## 7. Enforcement & setup

A POSIX-sh hook lives at `.githooks/commit-msg` and validates the header against
the rules above — **no npm / commitlint dependency**, matching this repo's
bootstrap-limited toolchain. Wire it once per clone:

```bash
git config core.hooksPath .githooks      # enable the commit-msg hook
git config commit.template .gitmessage   # optional: prefilled message template
```

The hook guards only the header (`type(scope): subject`, allowed types, length,
no trailing period) so history stays machine-parseable; the body and footer are
left to the author.
