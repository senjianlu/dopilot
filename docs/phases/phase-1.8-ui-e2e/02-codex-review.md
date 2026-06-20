# 02 · Phase 1.8 UI E2E — Codex Review

## Verdict

Accepted.

Claude's change adds browser-level page workflow coverage for the Phase 1.8 UI
without changing dispatch/runtime behavior. The new smoke runner uses the same
Docker stack shape requested for acceptance: one server, three agents, clean
compose volumes, and the bundled production SPA served by the server container.

## Findings

No blocking findings.

## Review Notes

- The Playwright specs cover the requested page-functionality path: login,
  navigation, nodes, build artifact upload and direct run, execution template
  create/run, task detail and logs, task list navigation, schedule create and
  trigger-now, and node offline/online/delete state changes.
- The UI smoke script starts from `docker compose down -v`, so old test data is
  removed before the browser run.
- The browser target is `http://localhost:5000`, which is the Docker-served SPA,
  not a Vite development server.
- The specs are intentionally serial and non-retried because they mutate shared
  backend state. This is acceptable for a clean-volume smoke test.
- The visible build artifact format column is consistent with Phase 1.8's
  package-format concept and gives the browser test a real page-level assertion
  for `egg`.
- The nodes page currently does not expose a live green scrapyd-running signal
  from heartbeat data. The test asserts the authoritative healthy schedulable
  node badge plus visible scrapyd cell; the existing bash smoke remains the
  runtime oracle for live agent/scrapyd health and dispatch logs.

## Residual Risk

The UI smoke is a workflow proof, not exhaustive visual regression coverage. It
does not assert every form field variation or every schedule override variant,
but it covers the requested end-to-end page behavior on the real Docker stack.
