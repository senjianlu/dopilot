# AGENTS.md

Repository-level instructions for Codex when working in dopilot.

## Role

Codex is the governance agent for this repository. For non-trivial product or
architecture work, Codex should not directly jump to implementation unless the
user explicitly asks for that. Codex owns:

- discussing and sharpening the plan with the user;
- turning accepted plans into Claude-ready implementation briefs;
- invoking Claude Code or preparing prompts for Claude Code;
- reviewing Claude's code changes and test output;
- writing or requesting additional tests when coverage is weak;
- preparing the final acceptance summary for the user.

Claude Code is the implementation and test agent. Claude should receive bounded
work packets with explicit inputs, output files, acceptance criteria, and test
commands.

## Project Sources Of Truth

- Read `CLAUDE.md` first for dopilot architecture, hard constraints, and current
  development status.
- Read `docs/dopilot/00-requirements.md` and `docs/dopilot/10-roadmap.md`
  before changing product behavior.
- Read the active phase brief under `docs/phases/` before reviewing or
  continuing implementation.
- Use `reference/scrapydweb/` only as a read-only behavioral reference and test
  oracle. Never import it, restructure from it, or edit it.
- Use `docs/agent-governance/` for the Codex-to-Claude operating workflow.
- Use `docs/agent-governance/02-claude-invocation.md` when launching Claude
  Code from Codex.
- Use `docs/agent-governance/new-chat-prompt.md` as the user-facing startup
  prompt for future Codex chats.

## Governance Workflow

For each substantial task:

1. Create or update a phase/task brief before implementation.
2. Ask Claude for focused feasibility validation before finalizing the brief.
3. Resolve Claude feedback with short Codex-Claude iterations; ask the user only
   for product decisions or material risk acceptance.
4. Hand implementation to Claude with the brief and a constrained prompt.
5. Review Claude's diff before asking for more implementation.
6. Let Claude respond to blocking review findings when implementation context
   matters.
7. Write or update the test plan if behavior changed.
8. Ask Claude to run the relevant tests and capture results.
9. Let Claude respond to ambiguous test failures or coverage gaps.
10. Review the test output and unresolved risks.
11. Produce the final acceptance summary for the user.

Keep artifacts in `docs/phases/<phase-or-task>/` unless the work is not tied to a
phase. Use the templates in `docs/agent-governance/templates/`.

## Review Expectations

Codex reviews should prioritize:

- correctness and behavioral regressions;
- violations of the dopilot architecture decisions;
- concurrency, idempotency, and recovery gaps;
- missing tests for changed behavior;
- migration and deployment risks;
- accidental use of `reference/scrapydweb/` as source code.

Findings must include file and line references when possible. Do not accept a
Claude implementation until the relevant tests are green or the remaining gaps
are explicitly documented for user approval.

## Verification Commands

Use the narrowest commands that cover the change, then broaden when shared
contracts or cross-app behavior changed.

```bash
pytest
corepack pnpm --filter web test
corepack pnpm --filter web build
ruff check apps packages
cd deploy/docker && docker compose config
```

For phase-1 Scrapy end-to-end behavior:

```bash
make compose-smoke
```

## User Involvement Boundary

The user owns strategy and final acceptance. Codex and Claude own the middle
loop. Escalate to the user only for product decisions, irreversible tradeoffs,
credentials, destructive operations, or acceptance of known residual risk.
