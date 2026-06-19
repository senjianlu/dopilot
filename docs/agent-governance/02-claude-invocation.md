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

## Required Prompt Contract

Every Claude prompt should specify:

- task name and active brief;
- required context files;
- in-scope and out-of-scope paths;
- expected report file path;
- required commands;
- what to do if permissions or commands fail.

Use `templates/claude-implementation-prompt.md` as the base.
Use `templates/claude-feasibility-prompt.md` before finalizing a brief.
