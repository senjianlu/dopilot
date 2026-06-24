# Claude Docker/E2E Verification Prompt: Built-In Runtime Context

You are Claude Code working in the dopilot repository.

## Assignment

Run end-to-end verification for the built-in artifact refresh and runtime
context logging changes.

This is a test/verification task. Do not change implementation code unless a
minor test helper/report edit is needed. If you find a product or implementation
bug, report it with exact evidence instead of silently patching.

## User-Required Test Points

1. Build the Docker image from the current working tree.
2. Actually start the web page and verify the new built-in Scrapy crawler and
   built-in Script run and print Dopilot runtime context at execution time.

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/task-runtime-context/00-brief.md`
- `docs/phases/task-runtime-context/07-acceptance.md`
- `docs/phases/task-builtin-artifact-refresh/00-brief.md`
- `docs/phases/task-builtin-artifact-refresh/07-acceptance.md`
- `deploy/docker/Dockerfile`
- `deploy/docker/docker-compose.yml`
- existing Playwright helpers under `apps/web/e2e/`

## Permissions / Allowed Operations

You are authorized for this verification task to run:

- Docker image build commands, including `docker build`.
- Docker Compose commands under an isolated project name, including:
  - `docker compose -p <unique-project> up -d`
  - `docker compose -p <unique-project> logs`
  - `docker compose -p <unique-project> down -v --remove-orphans`
- Browser automation / Playwright commands needed to use the actual web page.
- `curl`, `.venv/bin/python`, `corepack pnpm`, and focused shell inspection
  commands.

Safety boundary:

- Use a unique project name such as `dopilot-runtime-context-e2e`.
- Do not stop or delete containers/volumes outside that compose project.
- Use `down -v` only for the unique test project.
- Do not push images or contact Docker Hub except for base-image pulls required
  by the local build.

## Required Verification Flow

### 1. Build Image

From repo root:

```bash
docker build -f deploy/docker/Dockerfile -t rabbir/dopilot:latest .
```

Record the final build outcome and image id/digest if available.

### 2. Start A Clean Test Stack

Use a unique compose project:

```bash
cd deploy/docker
docker compose -p dopilot-runtime-context-e2e down -v --remove-orphans
docker compose -p dopilot-runtime-context-e2e up -d
```

Wait for server and agents to become healthy. Record:

```bash
docker compose -p dopilot-runtime-context-e2e ps
docker compose -p dopilot-runtime-context-e2e logs --tail=200 server
```

### 3. Verify Page Is Actually Running

Open/use the real web app at `http://localhost:5000`.

Credentials from the compose file:

- username: `admin`
- password: `change-me`

You may use existing Playwright helpers/spec patterns, or write a temporary
Playwright/scripted browser check. The result must prove the page loaded and the
flow was exercised through the UI, not only via direct DB inspection.

### 4. Verify Built-In Scrapy Runtime Context Logging

Through the web page:

- Find/select the built-in `dopilot_clock` Scrapy artifact/template flow, or
  create a template from the built-in artifact if needed.
- Run the `clock` spider.
- Use a short command override if the UI allows it, for example:

```text
scrapy crawl clock -a duration_seconds=1
```

This keeps the smoke fast while still testing startup logging. If using the
default command is more practical, note that it defaults to 45 seconds.

Verify the task/execution log contains all of:

- `dopilot env:`
- `dopilot settings:`
- `DOPILOT_TASK_ID`
- `DOPILOT_EXECUTION_ID`
- `DOPILOT_RUNTIME_CONTEXT`

It is acceptable that Scrapy runtime context appears under settings rather than
OS env, because the runtime-context task intentionally injects Scrapy context as
Scrapy settings.

### 5. Verify Built-In Script Runtime Context Logging

Through the web page:

- Find/select the built-in `dopilot-demo` Python wheel artifact/template flow,
  or create a template from the built-in artifact if needed.
- Run the script using the command:

```text
DOPILOT_DEMO_URL=http://server:5000/api/v1/health python -m main
```

Verify the task/execution log contains all of:

- `dopilot-demo: dopilot env:`
- `DOPILOT_TASK_ID`
- `DOPILOT_EXECUTION_ID`
- `DOPILOT_RUNTIME_CONTEXT`
- `dopilot-demo: requesting http://server:5000/api/v1/health`

### 6. Optional But Useful: Existing-Volume Refresh

If time permits, without deleting the compose project volume:

- Restart the server container.
- Confirm startup import does not duplicate built-in artifacts.

This is secondary to the two user-required test points.

### 7. Cleanup

After collecting evidence:

```bash
cd deploy/docker
docker compose -p dopilot-runtime-context-e2e down -v --remove-orphans
```

If cleanup fails, report it clearly.

## Report

Write the final report to:

`docs/phases/task-builtin-artifact-refresh/08-claude-docker-e2e-report.md`

Include:

- commands run and exact outcomes;
- Docker build result;
- compose health/status evidence;
- browser/page verification method;
- Scrapy task id / execution id and relevant log excerpts;
- Script task id / execution id and relevant log excerpts;
- cleanup result;
- unresolved failures or risks.

Keep excerpts short but sufficient to prove the required strings appeared.
