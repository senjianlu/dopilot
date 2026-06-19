# dopilot unified image (server + bundled Web UI + agent).
#
# Build context = repo ROOT (compose passes context: ../..).
# Base image is glibc (python:3.12-slim), never Alpine: parent-death subprocess
# signaling relies on glibc libc.so.6 prctl.
#
# This image contains both runtime roles:
#   - server mode: dopilot-server + bundled Vue SPA + Alembic migrations
#   - agent mode: dopilot-agent + scrapy/scrapyd runtime
#
# The role is selected at container start with the command, e.g.
# `dopilot-server ...` or `dopilot-agent ...`. The image MUST NOT contain
# reference/ (read-only scrapydweb behavioral reference).

# ---- Stage: build web -----------------------------------------------------
FROM node:22-slim AS web-build

WORKDIR /build

COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json

RUN corepack enable \
    && pnpm install --filter web --frozen-lockfile

COPY apps/web ./apps/web

RUN pnpm --filter web build

# ---- Stage: build Python wheels ------------------------------------------
FROM python:3.12-slim AS py-deps

WORKDIR /build

# Make wheel builds resilient to transient PyPI / pythonhosted hiccups.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10

RUN pip install --no-cache-dir wheel

COPY packages/protocol ./packages/protocol
COPY apps/server ./apps/server
COPY apps/agent ./apps/agent

RUN pip wheel --wheel-dir=/wheels \
    ./packages/protocol \
    ./apps/server \
    ./apps/agent

# ---- Stage: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=py-deps /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

# Agent-managed Scrapy runtime. These are image-level dependencies because the
# agent spawns `scrapyd` as a managed subprocess and deploys eggs into it.
RUN pip install --no-cache-dir 'scrapy>=2.11,<3' 'scrapyd>=1.4,<2'

# Fail the build early if the scrapyd console script did not land on PATH.
RUN command -v scrapyd >/dev/null || (echo "scrapyd console script missing from PATH" >&2; exit 1)

# Alembic assets so the same image can run `alembic upgrade head`.
COPY apps/server/alembic.ini ./alembic.ini
COPY apps/server/migrations ./migrations

# Built Vue SPA. dopilot_server.app serves this directory when index.html is
# present, while /api/* remains API-only.
COPY --from=web-build /build/apps/web/dist ./web

ENV DOPILOT_WEB_DIST=/app/web
ENV DOPILOT_CONFIG=/app/configs/server.toml
ENV DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
ENV AGENT_WORKDIR=/agent-data

RUN mkdir -p /agent-data /server-data
VOLUME ["/agent-data", "/server-data"]

EXPOSE 5000 6800

# Default to server mode for `docker run rabbir/dopilot:latest`; compose
# overrides this for migrate and agent roles.
CMD ["dopilot-server", "-b", "0.0.0.0", "-p", "5000"]
