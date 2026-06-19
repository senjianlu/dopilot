#!/usr/bin/env bash
#
# Print the dependency-input hash used for Docker base image tags.
#
# Keep this script as the single source of truth for both local builds and
# GitHub Actions. The hash intentionally tracks dependency inputs and the base
# Dockerfile, not normal application source files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

sha256sum \
  deploy/docker/Dockerfile.base \
  pnpm-lock.yaml \
  pnpm-workspace.yaml \
  apps/web/package.json \
  apps/server/pyproject.toml \
  apps/agent/pyproject.toml \
  packages/protocol/pyproject.toml \
  | sha256sum \
  | cut -c1-12
