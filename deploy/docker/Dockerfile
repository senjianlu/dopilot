# dopilot unified image (server + bundled Web UI + agent).
#
# Build context = repo ROOT (compose passes context: ../..).
# Base image is glibc (python:3.12-slim), never Alpine: parent-death subprocess
# signaling relies on glibc libc.so.6 prctl.
#
# This image contains both runtime roles:
#   - server mode: dopilot-server + bundled Next static export web UI + Alembic
#   - agent mode: dopilot-agent + scrapy/scrapyd runtime
#
# The role is selected at container start with the command, e.g.
# `dopilot-server ...` or `dopilot-agent ...`. The image MUST NOT contain any
# upstream scrapydweb code; `.dockerignore` keeps a defensive `reference/`
# exclusion even though no local snapshot exists in the tree anymore.

ARG DOPILOT_PY_BASE_IMAGE=rabbir/dopilot-py-base:latest
ARG DOPILOT_WEB_BASE_IMAGE=rabbir/dopilot-web-base:latest

# ---- Stage: build web -----------------------------------------------------
FROM ${DOPILOT_WEB_BASE_IMAGE} AS web-build

WORKDIR /build

COPY apps/web ./apps/web

# Next.js static export (output: "export") -> apps/web/out.
RUN pnpm --filter web build

# ---- Stage: build Python wheels ------------------------------------------
FROM ${DOPILOT_PY_BASE_IMAGE} AS py-deps

WORKDIR /build

COPY packages/protocol ./packages/protocol
COPY apps/server ./apps/server
COPY apps/agent ./apps/agent

RUN pip wheel --no-build-isolation --no-deps --wheel-dir=/wheels \
    ./packages/protocol \
    ./apps/server \
    ./apps/agent

# ---- Stage: runtime -------------------------------------------------------
FROM ${DOPILOT_PY_BASE_IMAGE} AS runtime

WORKDIR /app

COPY --from=py-deps /wheels /wheels
RUN pip install --no-cache-dir --no-deps /wheels/* \
    && rm -rf /wheels

# Built-in validation crawler artifact. Docker named volumes mounted at
# /server-data are initialized from this image content on first create.
COPY examples/scrapy_clock ./examples/scrapy_clock
RUN cd /app/examples/scrapy_clock \
    && python setup.py clean --all >/dev/null 2>&1 || true \
    && python setup.py bdist_egg \
    && mkdir -p /server-data/artifacts/scrapy \
    && python - <<'PY'
import hashlib, json
from datetime import UTC, datetime
from pathlib import Path

built = next(Path("/app/examples/scrapy_clock/dist").glob("*.egg"))
data = built.read_bytes()
sha = hashlib.sha256(data).hexdigest()
target = Path("/server-data/artifacts/scrapy") / f"{sha}.egg"
target.write_bytes(data)
manifest = {
    "sha256": sha,
    "filename": "dopilot_clock.egg",
    "project": "dopilot_clock",
    "version": f"sha256-{sha[:12]}",
    "spiders": ["clock"],
    "size_bytes": len(data),
    "uploaded_at": datetime.now(UTC).isoformat(),
    "valid": True,
}
(Path("/server-data/artifacts/scrapy") / f"{sha}.json").write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
    encoding="utf-8",
)
PY

# Built-in demo wheel artifact (phase 2b). Like the scrapy_clock egg above, this
# seeds /server-data so a clean-volume stack lists a runnable `python_wheel`
# artifact without a host upload. It reuses the server's own WheelArtifactStore,
# so the on-disk wheel bytes + manifest are byte-identical to an admin upload
# (same sha256 dedupe key the agent later fetches/installs).
COPY tests/fixtures/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl \
    /app/examples/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl
RUN python - <<'PY'
from pathlib import Path

from dopilot_server.artifacts.wheel_store import WheelArtifactStore

wheel = Path(
    "/app/examples/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl"
)
WheelArtifactStore("/server-data/artifacts").save(
    filename=wheel.name, content=wheel.read_bytes()
)
PY

# Alembic assets so the same image can run `alembic upgrade head`.
COPY apps/server/alembic.ini ./alembic.ini
COPY apps/server/migrations ./migrations

# Default configs baked into the image so the prebuilt image runs with no host
# config mounts. The role default config path is baked into each entrypoint
# (dopilot-server -> /app/configs/server.toml, dopilot-agent ->
# /app/configs/agent.toml), so there is NO global DOPILOT_CONFIG env (which would
# wrongly make the agent read the server TOML). compose env vars override
# per-agent fields like AGENT_ID. Advanced deployments may mount their own TOML
# over these baked paths; compose uses environment overrides for normal changes.
RUN mkdir -p /app/configs
COPY configs/server.docker.toml ./configs/server.toml
COPY configs/agent.example.toml ./configs/agent.toml

# Built Next.js static export. dopilot_server.app serves this directory (one
# HTML file per route + _next assets + 404.html) when index.html is present,
# while /api/* remains API-only.
COPY --from=web-build /build/apps/web/out ./web

ENV DOPILOT_WEB_DIST=/app/web
ENV DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
ENV AGENT_WORKDIR=/agent-data

RUN mkdir -p /agent-data /server-data
VOLUME ["/agent-data", "/server-data"]

EXPOSE 5000 6800

# Default to server mode for `docker run rabbir/dopilot:latest`; compose
# overrides this for migrate and agent roles.
CMD ["dopilot-server", "-b", "0.0.0.0", "-p", "5000"]
