# Docker/E2E Verification Report: Built-In Artifact Refresh

## Summary

Result: PASS.

The current working tree built into `rabbir/dopilot:latest`, the clean Docker
Compose stack became healthy, the real bundled web UI loaded at
`http://localhost:5000`, and both page-visible built-in artifacts ran through
the UI with the required Dopilot runtime-context log strings.

## Commands And Outcomes

### Docker Image Build

Command:

```bash
docker build -f deploy/docker/Dockerfile -t rabbir/dopilot:latest .
```

Outcome: passed.

Evidence:

- Build completed in 44.1s.
- Next.js web build completed during the Docker build.
- Python wheel build and built-in artifact seeding stages completed.
- Final image:
  - image id / digest: `sha256:8929db9236339f840e22d80491bcd70e2ac901f9d7f8185b9682bb61fd726658`
  - Docker build exported manifest: `sha256:60bacbbdb93e1eee1eee75a00aabfba0c4afe8b672292a0749c807b3f4460ed`
  - Docker build exported config: `sha256:734699be59a109622aba3a04702a1f70e27dd775b7efb4a28c9c9dbf3cde7ee9`
  - `docker image ls` reported `rabbir/dopilot:latest`, digest
    `sha256:8929db9236339f840e22d80491bcd70e2ac901f9d7f8185b9682bb61fd726658`,
    size `447MB`.

### Clean Compose Stack

Commands:

```bash
cd deploy/docker
docker compose -p dopilot-runtime-context-e2e down -v --remove-orphans
docker compose -p dopilot-runtime-context-e2e up -d
```

Outcome: passed.

Initial cleanup found no existing resources for the project. Compose then
created the isolated network and six named volumes, started PostgreSQL, Redis,
three agents, migration, and server. Migration exited successfully before the
server started.

Health/status evidence from `docker compose -p dopilot-runtime-context-e2e ps`:

```text
db               Up (healthy)   0.0.0.0:5432->5432/tcp
redis            Up (healthy)   6379/tcp
scrapy-agent-1   Up (healthy)
scrapy-agent-2   Up (healthy)
scrapy-agent-3   Up (healthy)
server           Up (healthy)   0.0.0.0:5000->5000/tcp
```

Server log evidence from `docker compose -p dopilot-runtime-context-e2e logs --tail=200 server`:

```text
Started server process [7]
Waiting for application startup.
Application startup complete.
Uvicorn running on http://0.0.0.0:5000
POST /api/v1/agents/scrapy-agent-1/heartbeat HTTP/1.1" 200 OK
POST /api/v1/agents/scrapy-agent-2/heartbeat HTTP/1.1" 200 OK
POST /api/v1/agents/scrapy-agent-3/heartbeat HTTP/1.1" 200 OK
GET /api/v1/health HTTP/1.1" 200 OK
```

Additional health check:

```bash
curl -fsS http://localhost:5000/api/v1/health
```

Outcome: passed. Response reported `status=ok`, `database=ok`, Redis version
`7.4.9`, PostgreSQL reachable, and `nodes.total=3`, `nodes.online=3`,
`nodes.healthy=3`.

## Browser Verification Method

I used Playwright Chromium against the real production SPA served by the Docker
server container at `http://localhost:5000`. The browser flow:

1. Loaded `/login`.
2. Logged in with compose credentials `admin` / `change-me`.
3. Waited for `app-shell`.
4. Opened the Artifacts page and verified the built-in rows:
   - `dopilot_clock`, type `scrapy`, format `egg`
   - `dopilot-demo`, type `python_wheel`, format `wheel`
5. Created a Scrapy execution template from
   `dopilot_clock · dopilot_clock.egg`.
6. Ran the Scrapy template from the Templates page and read the task detail log
   through the UI log viewer.
7. Created a Python wheel execution template from
   `dopilot-demo · dopilot_demo-0.1.0-py3-none-any.whl`.
8. Ran the Python wheel template from the Templates page and read the task
   detail log through the UI log viewer.

No direct DB-only inspection was used to satisfy the required runtime-context
checks; the task runs and log assertions were exercised through the page.

## Built-In Scrapy Runtime Context

UI-created command:

```text
scrapy crawl clock -a duration_seconds=1
```

Outcome: passed.

Evidence:

- task id: `a5511586d4dd4d9583d918ac443283e8`
- selected execution id: `01afd989fbcb4b58aa8fa900efbaeed0`
- execution count: `3`
- task status: `complete`

Relevant UI log excerpt:

```text
2026-06-24 02:20:53 [clock] INFO: dopilot env: {'DOPILOT_AGENT_TOKEN': 'change-me-agent-token', 'DOPILOT_DATABASE_URL': 'postgresql+psycopg://dopilot:dopilot@db:5432/dopilot', 'DOPILOT_REDIS_URL': 'redis://:change-me-redis-pass@redis:6379/0', 'DOPILOT_WEB_DIST': '/app/web'}
2026-06-24 02:20:53 [clock] INFO: dopilot settings: {'DOPILOT_AGENT_ID': 'scrapy-agent-1', 'DOPILOT_ARTIFACT_TYPE': 'scrapy', 'DOPILOT_EXECUTION_ID': '01afd989fbcb4b58aa8fa900efbaeed0', 'DOPILOT_EXECUTION_TEMPLATE_ID': 'e8b32a8ea8a541f7afe78584b5167e1a', 'DOPILOT_RUNTIME_CONTEXT': '{"agent_id":"scrapy-agent-1","artifact_type":"scrapy","execution_id":"01afd989fbcb4b58aa8fa900efbaeed0","execution_template_id":"e8b32a8ea8a541f7afe78584b5167e1a","schedule_id":null,"source":"template","task_id":"a5511586d4dd4d9583d918ac443283e8","task_type":"scrapy"}', 'DOPILOT_SCHEDULE_ID': '', 'DOPILOT_TASK_ID': 'a5511586d4dd4d9583d918ac443283e8', 'DOPILOT_TASK_SOURCE': 'template', 'DOPILOT_TASK_TYPE': 'scrapy'}
```

Required strings verified in the page log:

- `dopilot env:`
- `dopilot settings:`
- `DOPILOT_TASK_ID`
- `DOPILOT_EXECUTION_ID`
- `DOPILOT_RUNTIME_CONTEXT`

## Built-In Script Runtime Context

UI-created command:

```text
DOPILOT_DEMO_URL=http://server:5000/api/v1/health python -m main
```

Outcome: passed.

Evidence:

- task id: `fa5b30ded8ca43b192490408b0a0cfb5`
- selected execution id: `601e0b175ba6482280b2bf46fb6a2073`
- execution count: `3`
- task status: `complete`

Relevant UI log excerpt:

```text
dopilot-demo: dopilot env:
  "DOPILOT_EXECUTION_ID": "601e0b175ba6482280b2bf46fb6a2073",
  "DOPILOT_RUNTIME_CONTEXT": "{\"agent_id\":\"scrapy-agent-1\",\"artifact_type\":\"python_wheel\",\"execution_id\":\"601e0b175ba6482280b2bf46fb6a2073\",\"execution_template_id\":\"947a9d83de75492ca04024dfc324ab0e\",\"schedule_id\":null,\"source\":\"template\",\"task_id\":\"fa5b30ded8ca43b192490408b0a0cfb5\",\"task_type\":\"python_wheel\"}",
  "DOPILOT_TASK_ID": "fa5b30ded8ca43b192490408b0a0cfb5",
dopilot-demo: requesting http://server:5000/api/v1/health
```

Required strings verified in the page log:

- `dopilot-demo: dopilot env:`
- `DOPILOT_TASK_ID`
- `DOPILOT_EXECUTION_ID`
- `DOPILOT_RUNTIME_CONTEXT`
- `dopilot-demo: requesting http://server:5000/api/v1/health`

## Optional Existing-Volume Refresh Check

Before restarting the server, PostgreSQL row counts were:

```text
 artifact_type |     name      | rows
---------------+---------------+------
 python_wheel  | dopilot-demo  |    1
 scrapy        | dopilot_clock |    1
```

Command:

```bash
docker compose -p dopilot-runtime-context-e2e restart server
```

Outcome: passed. The server returned to `running healthy`.

After restart, the same query returned the same counts:

```text
 artifact_type |     name      | rows
---------------+---------------+------
 python_wheel  | dopilot-demo  |    1
 scrapy        | dopilot_clock |    1
```

This confirms the startup import did not duplicate the built-in artifacts for
the existing compose volume.

## Cleanup

Command:

```bash
cd deploy/docker
docker compose -p dopilot-runtime-context-e2e down -v --remove-orphans
```

Outcome: passed.

Compose removed:

- server, migrate, db, redis, and all three agent containers;
- all six `dopilot-runtime-context-e2e_*` named volumes;
- the `dopilot-runtime-context-e2e_default` network.

Post-cleanup inspection found no remaining containers or volumes with
`com.docker.compose.project=dopilot-runtime-context-e2e`.

## Unresolved Failures Or Risks

None found in this verification pass.
