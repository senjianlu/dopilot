#!/usr/bin/env bash
#
# Build dopilot's local dependency base images.
#
# The compose file defaults to these local tags:
#   rabbir/dopilot-py-base:local
#   rabbir/dopilot-web-base:local
#
# A content hash tag is also written for traceability. The hash intentionally
# tracks dependency inputs and this base Dockerfile, not normal application
# source files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

HASH="$("${SCRIPT_DIR}/docker-deps-hash.sh")"

PY_IMAGE="${DOPILOT_PY_BASE_IMAGE:-rabbir/dopilot-py-base:local}"
WEB_IMAGE="${DOPILOT_WEB_BASE_IMAGE:-rabbir/dopilot-web-base:local}"
PY_HASH_IMAGE="rabbir/dopilot-py-base:${HASH}"
WEB_HASH_IMAGE="rabbir/dopilot-web-base:${HASH}"

printf 'Building dopilot dependency base images (hash: %s)\n' "${HASH}"
printf '  Python: %s  %s\n' "${PY_IMAGE}" "${PY_HASH_IMAGE}"
printf '  Web:    %s  %s\n' "${WEB_IMAGE}" "${WEB_HASH_IMAGE}"

docker build --pull=false \
  -f deploy/docker/Dockerfile.base \
  --target py-runtime \
  -t "${PY_IMAGE}" \
  -t "${PY_HASH_IMAGE}" \
  .

docker build --pull=false \
  -f deploy/docker/Dockerfile.base \
  --target web-deps \
  -t "${WEB_IMAGE}" \
  -t "${WEB_HASH_IMAGE}" \
  .

printf 'Base images ready.\n'
