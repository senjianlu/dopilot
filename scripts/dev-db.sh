#!/usr/bin/env bash
# Start only the local Postgres container (compose db service) for development.
# Usage: scripts/dev-db.sh [up|down|logs]   (default: up)
set -euo pipefail

# Resolve repo root from this script's location, then enter the compose dir.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/deploy/docker"

cmd="${1:-up}"

cd "${COMPOSE_DIR}"
case "${cmd}" in
  up)
    docker compose up -d db
    ;;
  down)
    docker compose stop db
    ;;
  logs)
    docker compose logs -f db
    ;;
  *)
    echo "usage: $(basename "$0") [up|down|logs]" >&2
    exit 2
    ;;
esac
