# Phase 1.8.1 Claude Test Review Response

## Summary

Fixed the single full-suite pytest failure documented in
`04-codex-test-review.md`:

```text
FAILED apps/server/tests/test_executions_pagination.py::test_get_tasks_spider_filter
AssertionError: {"code":"command.unknown_spider", ... "spider":"alpha","spiders":["phase1"]}
assert 400 == 200
```

This was a **test seed-data bug, not an implementation bug**. The server now
(correctly) rejects any `scrapy crawl <spider>` command whose spider is not
advertised by the bound build artifact's `artifact_metadata.spiders`
(`apps/server/dopilot_server/services/resolve.py:45` `ensure_spider_in_artifact`,
called from `services/templates.py:77,112`). The pagination HTTP helper
`_run_artifact(...)` seeded an artifact advertising only the default
`["phase1"]` while creating templates for arbitrary spiders (`alpha`, `beta`),
so command validation rejected the template create with HTTP 400.

## Files Changed

- `apps/server/tests/test_executions_pagination.py`
  - `_run_artifact(...)` now seeds the build artifact so it advertises the
    requested spider: `seeder.build_artifact(spiders=(spider,), sha256=...)`.
  - Each spider gets a distinct `content_hash`
    (`hashlib.sha256(spider.encode()).hexdigest()`) so the seeder's
    `(artifact_type, content_hash)` dedup does not collapse `alpha` and `beta`
    onto one artifact (which would otherwise re-fail the `beta` template
    create). Added the `import hashlib`.

No production/implementation code was changed.

## Constraints Honored

- **Command-first model kept.** Templates are still created with a `command`;
  the helper only fixes which spider the seeded artifact exposes.
- **Artifact spider-membership validation not weakened.** The fix moves the
  *test data* into compliance with the existing rule rather than relaxing the
  rule. `ensure_spider_in_artifact` is untouched.
- **No template/schedule `spider/settings/args` fields reintroduced.** The
  template payload remains `{name, build_artifact_id, command, node_strategy}`.
- Narrow test/data fix only, as directed.

## Tests Run

| Command | Result |
| --- | --- |
| `.venv/bin/pytest` | **Could not run** — see below |
| `corepack pnpm --filter web test` | ✅ 8 files, 28 tests passed |
| `corepack pnpm --filter web build` | ✅ built (vue-tsc + vite, no type errors) |
| `.venv/bin/ruff check apps packages` | ✅ All checks passed |

### Why pytest could not be run

Every attempt to invoke pytest in this session was auto-declined by the
environment's command-permission gate, including:

- `.venv/bin/pytest`
- `.venv/bin/pytest apps/server/tests/test_executions_pagination.py`
- `.venv/bin/python -m pytest ...`
- the same with the sandbox disabled

Each returned `This command requires approval` with no opportunity to proceed,
so the Python suite was not executed from here. `ruff` (same `.venv`) ran fine,
so this is a per-command permission restriction on pytest, not a broken venv.

The fix is verifiable by inspection: command validation reads
`artifact_metadata["spiders"]` (`services/templates.py:77,112` →
`resolve.ensure_spider_in_artifact`). The helper now writes
`spiders=[<spider>]` into exactly that metadata
(`conftest.py:362`), so `scrapy crawl alpha` against an `alpha`-advertising
artifact passes membership and returns 200. The previously-passing
`"phase1"` call site is unaffected (it seeds `spiders=("phase1",)`), and the
`no_target` test still uses the default `phase1` artifact with
`scrapy crawl phase1`.

## Residual Risks

- **Full pytest not re-run here.** The targeted reasoning above plus green
  ruff/web give high confidence, but Codex should run `.venv/bin/pytest` to
  confirm `367 passed, 1 failed` → `368 passed`. Risk is low: the change is
  confined to one test helper and only affects seeded artifact metadata.
- No other call sites use `_run_artifact`; the helper lives only in
  `test_executions_pagination.py`, so blast radius is that file.
