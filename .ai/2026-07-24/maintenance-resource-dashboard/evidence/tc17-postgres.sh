#!/usr/bin/env bash
# TC-17: exercise the PostgreSQL-only resource-stats SQL path (pg_total_relation_size /
# pg_database_size / row counts / effective-time ages) against a REAL, migrated
# PostgreSQL. Spins up a throwaway postgres container, runs `alembic upgrade head`,
# then runs the DOPILOT_TEST_PG_URL-gated test. Fully non-interactive.
set -uo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
PORT=55432
IMAGE=postgres:16

echo "=== docker run $IMAGE (port $PORT) ==="
CID=$(docker run -d --rm \
  -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=dopilot \
  -p 127.0.0.1:${PORT}:5432 "$IMAGE") || { echo "docker run failed"; exit 1; }
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT
echo "container: $CID"

echo "=== wait for readiness ==="
ready=0
for _ in $(seq 1 60); do
  if docker exec "$CID" pg_isready -U postgres -d dopilot >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[ "$ready" = 1 ] || { echo "postgres not ready"; exit 1; }
echo "postgres ready"

export DOPILOT_DATABASE_URL="postgresql+psycopg://postgres:pw@127.0.0.1:${PORT}/dopilot"
export DOPILOT_TEST_PG_URL="$DOPILOT_DATABASE_URL"

echo "=== alembic upgrade head ==="
( cd apps/server && alembic upgrade head ) || { echo "alembic failed"; exit 1; }

echo "=== pytest TC-17 (real PostgreSQL) ==="
python -m pytest apps/server/tests/test_resource_stats.py -k tc17 -v
rc=$?
echo "=== pytest exit: $rc ==="
exit $rc
