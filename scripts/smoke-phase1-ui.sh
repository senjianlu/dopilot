#!/usr/bin/env bash
#
# dopilot Phase 1.8 BROWSER UI e2e smoke.
#
# Brings up the SAME clean-volume one-server / three-agent Docker stack as
# scripts/smoke-phase1.sh (PostgreSQL + Redis + migrate + server + scrapy-agent
# {1,2,3}), waits until it is usable, then runs the Playwright browser e2e specs
# against the BUNDLED PRODUCTION SPA the server container serves at
# http://localhost:5000 — NOT a Vite dev server.
#
# This is the UI counterpart to scripts/smoke-phase1.sh:
#   * smoke-phase1.sh    = exact multi-agent dispatch / count / log ORACLE (bash).
#   * smoke-phase1-ui.sh = browser page-workflow proof (Playwright/Chromium).
#
# Usage:
#   scripts/smoke-phase1-ui.sh            # clean-volume UI e2e, tears down after
#   KEEP_UP=1 scripts/smoke-phase1-ui.sh  # leave the stack up on success (debug)
#   E2E_GREP="nodes" scripts/smoke-phase1-ui.sh   # run a subset of specs
#
# Idempotent: always starts from `docker compose down -v` and always tears down
# on exit unless KEEP_UP=1 and the run passed.
#
# Requires: docker + docker compose v2, curl, python3, corepack/pnpm (host), and
# the Playwright Chromium browser (auto-installed here if missing).

set -euo pipefail

# ---- locations -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/deploy/docker"
COMPOSE_BASE="${COMPOSE_DIR}/docker-compose.yml"
COMPOSE_E2E="${COMPOSE_DIR}/docker-compose.e2e.yml"
SERVER_CONFIG="${REPO_ROOT}/configs/server.docker.toml"
WEB_DIR="${REPO_ROOT}/apps/web"

SERVER="http://localhost:5000"
ADMIN_USER="admin"
ADMIN_PASS="change-me"

# The three agents (agent_id -> compose service key).
AGENT_IDS=(scrapy-agent-1 scrapy-agent-2 scrapy-agent-3)
declare -A SERVICE_OF=(
  [scrapy-agent-1]=agent
  [scrapy-agent-2]=scrapy-agent-2
  [scrapy-agent-3]=scrapy-agent-3
)

HEALTH_TIMEOUT=240   # per service_healthy wait (3 agents + image build)
NODES_TIMEOUT=240    # wait for 3 healthy schedulable nodes via the API

# ---- output helpers --------------------------------------------------------
step() { printf '\n==> %s\n' "$*"; }
info() { printf '  ---- %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*" >&2; }
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }

dc() { docker compose -f "${COMPOSE_BASE}" -f "${COMPOSE_E2E}" "$@"; }

# ---- diagnostics dump (on failure) -----------------------------------------
dump_diagnostics() {
  local why="$1"
  printf '\n\033[31m==== UI SMOKE DIAGNOSTICS (%s) ====\033[0m\n' "${why}" >&2
  printf '\n-- docker compose ps --\n' >&2
  dc ps >&2 2>&1 || true
  printf '\n-- server logs (tail 80) --\n' >&2
  dc logs --tail 80 server >&2 2>&1 || true
  for aid in "${AGENT_IDS[@]}"; do
    printf '\n-- %s (%s) logs (tail 40) --\n' "${aid}" "${SERVICE_OF[$aid]}" >&2
    dc logs --tail 40 "${SERVICE_OF[$aid]}" >&2 2>&1 || true
  done
  if [ -d "${WEB_DIR}/test-results" ]; then
    printf '\n-- playwright artifacts (test-results) --\n' >&2
    find "${WEB_DIR}/test-results" -maxdepth 3 -type f >&2 2>&1 || true
  fi
}

# ---- teardown --------------------------------------------------------------
teardown() {
  step "Teardown: docker compose down -v"
  dc down -v --remove-orphans >/dev/null 2>&1 || true
}

cleanup_on_exit() {
  local rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf '\n\033[31mUI SMOKE FAILED\033[0m\n'
    dump_diagnostics "exit ${rc}"
  fi
  if [ "${rc}" -eq 0 ] && [ "${KEEP_UP:-0}" = "1" ]; then
    step "KEEP_UP=1 and smoke passed: leaving the stack running."
    return
  fi
  teardown
}
trap cleanup_on_exit EXIT

# ---- wait helpers ----------------------------------------------------------
wait_healthy() {
  local svc="$1" timeout="$2" deadline
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    local cid health state
    cid="$(dc ps -q "${svc}" 2>/dev/null || true)"
    if [ -n "${cid}" ]; then
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo "")"
      state="$(docker inspect -f '{{.State.Status}}' "${cid}" 2>/dev/null || echo "")"
      [ "${health}" = "healthy" ] && return 0
      [ "${state}" = "exited" ] && return 1
    fi
    [ "$(date +%s)" -ge "${deadline}" ] && return 1
    sleep 3
  done
}

wait_migrate() {
  local timeout="$1" deadline cid
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    cid="$(dc ps -aq migrate 2>/dev/null || true)"
    if [ -n "${cid}" ]; then
      local state code
      state="$(docker inspect -f '{{.State.Status}}' "${cid}" 2>/dev/null || echo "")"
      code="$(docker inspect -f '{{.State.ExitCode}}' "${cid}" 2>/dev/null || echo "")"
      if [ "${state}" = "exited" ]; then
        [ "${code}" = "0" ] && return 0 || return 1
      fi
    fi
    [ "$(date +%s)" -ge "${deadline}" ] && return 1
    sleep 3
  done
}

# Poll the API for exactly 3 healthy, scrapy- AND script-capable, schedulable
# nodes so the browser does not race agent registration / scrapyd startup.
# Phase 2b: the wheel run dispatches to `capabilities.script == true` nodes, so
# gate on script too — otherwise the wheel browser step could race the heartbeat.
wait_nodes_ready() {
  local timeout="$1" deadline token resp ready
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    token="$(curl -fsS -X POST "${SERVER}/api/v1/auth/login" \
      -H 'Content-Type: application/json' \
      -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" 2>/dev/null \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token") or "")' 2>/dev/null || true)"
    if [ -n "${token}" ]; then
      resp="$(curl -fsS "${SERVER}/api/v1/nodes" -H "Authorization: Bearer ${token}" 2>/dev/null || true)"
      ready="$(python3 - "${resp}" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
want = {"scrapy-agent-1", "scrapy-agent-2", "scrapy-agent-3"}
ok = set()
for n in data.get("nodes", []):
    if not n.get("id"):
        continue
    caps = n.get("capabilities") or {}
    if (
        n.get("status") == "healthy"
        and caps.get("scrapy")
        and caps.get("script")
        and n.get("scheduling_enabled")
        and not n.get("deleted_at")
    ):
        ok.add(n.get("agent_id"))
print("yes" if want <= ok else "no")
PY
)"
      [ "${ready}" = "yes" ] && return 0
    fi
    [ "$(date +%s)" -ge "${deadline}" ] && return 1
    sleep 3
  done
}

# =============================================================================
# Run
# =============================================================================
printf '======================================================================\n'
printf 'dopilot Phase 1.8 BROWSER UI e2e smoke (Playwright vs Docker SPA :5000)\n'
printf '  repo:   %s\n' "${REPO_ROOT}"
printf '  agents: %s\n' "${AGENT_IDS[*]}"
printf '======================================================================\n'

# --- ensure Playwright Chromium is available --------------------------------
step "Ensure Playwright Chromium is installed"
if ls "${HOME}/.cache/ms-playwright/"chromium-* >/dev/null 2>&1; then
  pass "Playwright Chromium already installed (skipping download)"
else
  info "Chromium not found; installing via Playwright"
  ( cd "${REPO_ROOT}" && corepack pnpm --filter web exec playwright install chromium )
  pass "Playwright Chromium installed"
fi

# --- clean-volume bring-up --------------------------------------------------
step "Clean-volume bring-up (down -v; build base images; up -d --build) — 3 agents"
dc down -v --remove-orphans >/dev/null 2>&1 || true
info "building dependency base images..."
"${REPO_ROOT}/scripts/build-docker-base.sh"
info "building + starting db, redis, migrate, server, and 3 agents..."
dc up -d --build

step "Wait for services (db, migrate, 3 agents, server)"
wait_healthy db "${HEALTH_TIMEOUT}" && pass "db healthy" \
  || { fail "db did not become healthy"; exit 1; }
wait_migrate "${HEALTH_TIMEOUT}" && pass "migrate completed (alembic upgrade head)" \
  || { fail "migrate did not complete"; dc logs migrate | tail -60 >&2; exit 1; }
for aid in "${AGENT_IDS[@]}"; do
  svc="${SERVICE_OF[$aid]}"
  wait_healthy "${svc}" "${HEALTH_TIMEOUT}" && pass "${aid} container healthy" \
    || { fail "${aid} (${svc}) did not become healthy"; exit 1; }
done
wait_healthy server "${HEALTH_TIMEOUT}" && pass "server healthy" \
  || { fail "server did not become healthy"; exit 1; }

step "Wait for 3 healthy, scrapy-capable, schedulable nodes (API)"
wait_nodes_ready "${NODES_TIMEOUT}" && pass "3 nodes healthy + schedulable" \
  || { fail "did not reach 3 healthy schedulable nodes"; exit 1; }

# --- run the browser e2e specs ----------------------------------------------
step "Run Playwright browser e2e (Chromium headless) vs ${SERVER}"
PW_ARGS=()
if [ -n "${E2E_GREP:-}" ]; then
  PW_ARGS+=(--grep "${E2E_GREP}")
fi
if E2E_BASE_URL="${SERVER}" \
   corepack pnpm --filter web exec playwright test "${PW_ARGS[@]}"; then
  pass "Playwright browser e2e passed"
else
  fail "Playwright browser e2e failed"
  exit 1
fi

step "UI smoke summary"
printf '\n\033[32mUI SMOKE PASSED\033[0m\n'
# Teardown happens in the EXIT trap (unless KEEP_UP=1).
