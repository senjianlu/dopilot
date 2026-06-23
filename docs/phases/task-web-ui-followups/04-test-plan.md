# Test Plan

## Server

Run the focused task-list pagination/filter suite:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client \
  .venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q
```

Coverage expected:

- service-level status filtering;
- status AND build-artifact filtering;
- HTTP `GET /api/v1/tasks?status=<valid>`;
- HTTP `GET /api/v1/tasks?status=<invalid>` returning 400.

## Web

Run the web unit suite:

```bash
corepack pnpm --filter web test
```

Coverage expected:

- schedules modal enabled switch create/edit behavior;
- schedules table quick-toggle payload/reload behavior;
- tasks status filter request params and preservation across refresh,
  pagination, and page-size changes;
- task detail execution/log tab ordering by agent id.

## Build

Run the static web build:

```bash
corepack pnpm --filter web build
```

Coverage expected:

- TypeScript/Next build succeeds;
- static export includes `/logo.svg` favicon metadata.
