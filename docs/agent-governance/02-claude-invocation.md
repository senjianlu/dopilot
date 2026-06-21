# Claude Invocation Protocol

Codex calls Claude Code as a bounded implementation/test subprocess through the
local `claude` CLI. The default mode is non-interactive print mode.

## Default Command Shape

```bash
claude -p \
  --permission-mode acceptEdits \
  --effort high \
  --output-format json \
  --name "<task-name>" \
  "$(cat <prompt-file>)"
```

Use `-p` so Claude performs one bounded task and exits. Codex then reviews the
exit status, generated files, stdout/stderr, and `git diff`.

## Permission Policy

Default mode:

```bash
--permission-mode acceptEdits
```

Rationale:

- file edits are allowed for implementation tasks;
- shell commands still need matching allow rules or explicit tool limits;
- permission failures return to Codex for review instead of becoming silent
  human-in-the-loop prompts.

For especially narrow test/report tasks, Codex may pass explicit tools:

```bash
--allowedTools "Read Edit Write Bash(.venv/bin/pytest *) Bash(git diff *) Bash(ruff check *)"
```

For implementation/test packets that need realistic verification, Codex should
grant Claude enough tool access up front instead of letting every test command
fail behind approval. This is appropriate for:

- `.venv/bin/pytest`, `.venv/bin/ruff`, `python -m pytest`;
- `corepack pnpm --filter web test` / `build` and other package scripts;
- `docker compose` / `scripts/smoke-phase1.sh` when the brief requires compose smoke;
- browser automation or screenshot checks when frontend behavior is in scope.

Prefer scoped allowlists for those command families, but do not make the
allowlist so narrow that Claude cannot perform the required verification. If a
packet explicitly requires Docker or browser checks, include those permissions in
the invocation prompt/command before starting Claude.

Do not use `--permission-mode bypassPermissions` or
`--dangerously-skip-permissions` as the default. Those modes are reserved for
trusted disposable sandboxes or explicit user-approved runs.

If Claude asks for a permission during `-p` and no rule can satisfy it, the
action is treated as denied or failed. Codex must inspect the output and decide
whether to narrow the prompt, add a specific allowed tool pattern, split the
task, or escalate to the user.

## Effort Selection

Codex should set effort explicitly instead of relying on Claude Code defaults.

| Work type | Effort |
| --- | --- |
| Documentation cleanup, small mechanical edits | `low` |
| Ordinary implementation or focused test additions | `medium` |
| Architecture-affecting work, migrations, Redis, scheduling, logs, auth, concurrency, recovery | `high` |
| Final review of high-risk changes or difficult incident/debug work | `high` or `xhigh` |

For the current dopilot Redis Streams phase, use:

```bash
--effort high
```

For feasibility validation before a brief, use `medium` by default and increase
to `high` only when the question involves migrations, concurrency, recovery, or
multiple subsystems.

## Completion Detection

Claude is considered done with a subprocess task only when all of these are
true:

- the `claude -p` process has exited;
- exit status and output have been captured;
- required report files exist and are complete;
- `git diff` matches the report;
- required commands are reported with exact pass/fail outcomes;
- Codex review has no unresolved blocking findings.

Claude saying "done" is not acceptance. Acceptance is a Codex decision after
review.

## Long-Running Progress Notes

For any Claude `-p` task that may run for a long time, Codex must ask Claude to
maintain a progress notes file inside the active phase/task directory:

```text
<phase-or-task>/claude-progress.md
```

At the start of the task, Claude should use the first few minutes to estimate
rough duration and write an initial note with:

- rough expected duration or size class, for example `<15m`, `15-45m`,
  `45-90m`, or `90m+`;
- proposed progress update cadence;
- current plan/checkpoints;
- likely long-running commands.

Claude should then update the file at meaningful checkpoints and before/after
long-running commands. The update cadence is a guideline chosen by Claude for
the task, not a hard timer. For very long implementation/test runs, a practical
cadence is often every 10-20 minutes, or after each major edit/test phase. Each
update should append or replace a short entry with:

- timestamp;
- current step;
- files or subsystems being inspected/edited;
- last command started or completed, when relevant;
- blockers, if any.

The progress file is not an implementation report and does not prove acceptance.
It exists as durable coordination state for long-running work, so Codex and a
future session can understand what Claude has tried, what is still running, and
what remains.

For short feasibility or documentation tasks, Codex may omit the progress-file
requirement. For migrations, Redis, scheduler, frontend build/test runs, compose
checks, or broad refactors, include it.

Codex must not kill or restart a Claude subprocess merely because a progress
note is late. Prefer non-invasive checks such as `ps`, reading the progress file,
or waiting for the subprocess result. Manual Claude process stops are always
user-controlled: Codex must not manually stop, kill, interrupt, or restart a
running Claude subprocess unless the user has explicitly approved that specific
stop action.

Codex monitoring should be accurate but cheap:

- prefer process metadata (`ps` elapsed time/CPU/memory), progress-file `stat`,
  report-file `stat`, and `git diff --stat` over interacting with Claude;
- use short, cancellable polling windows rather than long background sleeps;
- if a `claude -p` process exits, immediately stop any outstanding polling
  command and switch to capturing Claude's final JSON, report files, tests, and
  review;
- token and cost usage are normally available from Claude's final JSON result,
  not as a reliable live stream during `-p --output-format json`.

## Required Prompt Contract

Every Claude prompt should specify:

- task name and active brief;
- required context files;
- in-scope and out-of-scope paths;
- expected report file path;
- progress notes path and expected self-chosen cadence for long-running tasks;
- required commands;
- what to do if permissions or commands fail.

Use `templates/claude-implementation-prompt.md` as the base.
Use `templates/claude-feasibility-prompt.md` before finalizing a brief.
