# Codex Review

## Result

Accepted with Codex follow-up edits.

## Follow-up Edits

- Changed `deploy/docker/Dockerfile` default base-image args from local tags to
  public CI tags:
  - `rabbir/dopilot-py-base:latest`
  - `rabbir/dopilot-web-base:latest`
- Added an explicit `RUN mkdir -p /app/configs` before copying baked configs.
- Corrected the `docs/dopilot/08-docker-deployment.md` TOML excerpt from the
  stale static node list to `agents = []`, matching `configs/server.docker.toml`.
- Added README guidance that real secrets require mounting edited TOML files
  over `/app/configs/server.toml` and `/app/configs/agent.toml`.

## Verification

```bash
git diff --check
```

Passed.

```bash
cd deploy/docker && docker compose config -q && docker compose config --services
```

Passed. Services:

```text
redis
scrapy-agent-1
scrapy-agent-2
scrapy-agent-3
db
migrate
server
```

```bash
cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.build.yml config -q && docker compose -f docker-compose.yml -f docker-compose.build.yml config --services
```

Passed. Services:

```text
redis
scrapy-agent-1
scrapy-agent-2
scrapy-agent-3
db
migrate
server
```

```bash
rg -n "Makefile|compose-smoke|build-docker-base|docker-compose\.e2e|compose-up|compose-build|rabbir/dopilot-(py|web)-base:local|\bmake\s+[a-zA-Z_-]+" README.md README.zh-CN.md CONTRIBUTING.md AGENTS.md docs/agent-governance docs/dopilot scripts deploy/docker .github
```

Only benign match:

```text
docs/agent-governance/02-claude-invocation.md:50:Prefer scoped allowlists for those command families, but do not make the
```

## Not Run

- Full Python tests.
- Web tests/build.
- Docker image build.
- `scripts/smoke-phase1.sh`.

This task changed deployment files, scripts, and documentation only; compose
configuration was validated, but runtime image build/smoke remains the next
operational check before release.
