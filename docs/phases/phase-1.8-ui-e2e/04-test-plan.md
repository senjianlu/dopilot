# 04 · Phase 1.8 UI E2E Test Plan

## Behavior Under Test

- Browser access to the bundled production SPA served by the Docker server.
- Real authentication flow.
- Real page workflows for build artifacts, templates, schedules, tasks, logs,
  and nodes.
- One-server/three-agent runtime visibility in the UI.

## Browser Coverage

### Login And Navigation

- Visit `/login`.
- Log in with compose admin credentials.
- Verify the app shell appears.
- Navigate to nodes, build artifacts, execution templates, schedules, and tasks.

### Nodes Page

- Verify three agents render.
- Verify each shows Scrapy capability/healthy state through visible page data.
- Click offline on one node and verify the offline state appears.
- Click online and verify the node returns to schedulable state.
- Click delete on a node and verify deleted state appears.

### Build Artifacts Page

- Upload `tests/fixtures/scrapy_demo/eggs/demo_phase1.egg`.
- Verify a build artifact row appears with type `scrapy` and package format
  `egg`.
- Trigger a direct artifact run and verify navigation to task detail.

### Execution Templates Page

- Open create dialog.
- Select the uploaded build artifact.
- Select spider `phase1`.
- Verify project/version/spider-dependent fields populate.
- Verify the Scrapy command field is disabled/read-only.
- Submit and verify a template row appears.
- Run the template and verify navigation to task detail.

### Task Detail And Logs

- Verify task detail displays child executions.
- Verify log viewer can show demo markers:
  - `phase1 demo spider started`;
  - `phase1 demo spider done`.

### Tasks Page

- Verify created tasks are visible.
- Open a task detail page from the list.

### Schedules Page

- Create an interval schedule referencing the execution template.
- Trigger now.
- Verify navigation to a task detail page.

## Existing Gates

Keep these green:

```bash
.venv/bin/ruff check apps packages
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider
corepack pnpm --filter web test
corepack pnpm --filter web build
scripts/smoke-phase1.sh
```

## UI Smoke Command

Add and run:

```bash
scripts/smoke-phase1-ui.sh
```

Expected:

- starts clean Docker volumes;
- starts one server and three agents;
- runs Playwright against `http://localhost:5000`;
- exits 0;
- tears down the stack by default.

## Results

Claude fills this in `05-claude-test-report.md`.
