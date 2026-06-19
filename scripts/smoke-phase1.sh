#!/usr/bin/env bash
#
# dopilot phase-1 compose smoke: a repeatable, clean-volume end-to-end check of
# the real Scrapy execution chain (brief §7.6 / §10):
#
#   server API -> ScrapydExecutor -> agent /run -> in-agent scrapyd
#     -> scrapy demo:phase1 job -> agent tails job.log
#     -> server pulls log increments -> /server-data/logs + PostgreSQL index
#     -> server returns landed logs
#
# It builds the images, brings up db -> migrate -> agent -> server on FRESH
# volumes, uploads the committed demo egg, runs the demo spider, polls the
# execution to a terminal state, asserts the demo marker lines landed in the
# server logs, and asserts the final status is `complete`.
#
# Usage:
#   scripts/smoke-phase1.sh            # full clean-volume smoke
#   KEEP_UP=1 scripts/smoke-phase1.sh  # leave the stack up on success (debug)
#
# It is idempotent: it always starts from `docker compose down -v` and always
# tears down on exit unless KEEP_UP=1 and the run passed.
#
# Requires: docker + docker compose v2, curl, python3 (all on the HOST). No
# python venv is needed — JSON is parsed with the host python3.

set -euo pipefail

# ---- locations -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/deploy/docker"
EGG_PATH="${REPO_ROOT}/tests/fixtures/scrapy_demo/eggs/demo_phase1.egg"

# Demo project/spider are fixed phase-1 constants (see fixture README).
PROJECT="demo"
SPIDER="phase1"
VERSION="$(date +%s)"          # monotonic-ish egg version for this run

# Host-facing service URLs (compose publishes these ports).
SERVER="http://localhost:5000"
AGENT="http://localhost:6800"

# Admin creds match configs/server.docker.toml ([auth] is set -> web auth ON).
ADMIN_USER="admin"
ADMIN_PASS="change-me"

# Timeouts (seconds).
HEALTH_TIMEOUT=180            # per service_healthy wait
EXEC_TIMEOUT=120             # execution run -> terminal status

PASS_COUNT=0
FAIL_COUNT=0

# ---- output helpers --------------------------------------------------------
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; PASS_COUNT=$((PASS_COUNT + 1)); }
info() { printf '  ---- %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
fail() {
  printf '  \033[31mFAIL\033[0m %s\n' "$*" >&2
  FAIL_COUNT=$((FAIL_COUNT + 1))
  return 1
}

dc() { docker compose -f "${COMPOSE_DIR}/docker-compose.yml" "$@"; }

# ---- teardown --------------------------------------------------------------
teardown() {
  step "Teardown: docker compose down -v"
  dc down -v --remove-orphans >/dev/null 2>&1 || true
}

cleanup_on_exit() {
  local rc=$?
  if [ "${rc}" -eq 0 ] && [ "${KEEP_UP:-0}" = "1" ]; then
    step "KEEP_UP=1 and smoke passed: leaving the stack running."
    return
  fi
  teardown
}
trap cleanup_on_exit EXIT

# ---- python JSON helper ----------------------------------------------------
# json_get '<json>' '<dotted.path>'  -> prints the value or empty string.
# Supports dotted keys and [n] list indices, e.g. attempts[0].status.
json_get() {
  python3 - "$1" "$2" <<'PY'
import json, sys, re
data = json.loads(sys.argv[1] or "{}")
path = sys.argv[2]
cur = data
for part in re.findall(r'[^.\[\]]+|\[\d+\]', path):
    try:
        if part.startswith('[') and part.endswith(']'):
            cur = cur[int(part[1:-1])]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            cur = None
            break
    except (KeyError, IndexError, TypeError):
        cur = None
        break
if cur is None:
    print("")
elif isinstance(cur, bool):
    print("true" if cur else "false")
else:
    print(cur)
PY
}

# ---- wait helpers ----------------------------------------------------------
# wait_healthy <service> <timeout-seconds>
wait_healthy() {
  local svc="$1" timeout="$2" deadline
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    local cid health state
    cid="$(dc ps -q "${svc}" 2>/dev/null || true)"
    if [ -n "${cid}" ]; then
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo "")"
      state="$(docker inspect -f '{{.State.Status}}' "${cid}" 2>/dev/null || echo "")"
      if [ "${health}" = "healthy" ]; then
        return 0
      fi
      # A service with no healthcheck (or an exited one-shot) is handled by the
      # caller; here we only succeed on an explicit `healthy`.
      if [ "${state}" = "exited" ]; then
        return 1
      fi
    fi
    if [ "$(date +%s)" -ge "${deadline}" ]; then
      return 1
    fi
    sleep 3
  done
}

# wait_migrate <timeout-seconds>: the migrate service is one-shot; success is
# exit code 0 (compose `service_completed_successfully`).
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
    if [ "$(date +%s)" -ge "${deadline}" ]; then
      return 1
    fi
    sleep 3
  done
}

# ---- auth ------------------------------------------------------------------
# Logs in (web auth is ON in server.docker.toml) and echoes the bearer token.
login_token() {
  local resp token
  resp="$(curl -fsS -X POST "${SERVER}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" 2>/dev/null || true)"
  token="$(json_get "${resp}" "access_token")"
  printf '%s' "${token}"
}

# =============================================================================
# Run
# =============================================================================
printf '======================================================================\n'
printf 'dopilot phase-1 compose smoke\n'
printf '  repo:    %s\n' "${REPO_ROOT}"
printf '  egg:     %s\n' "${EGG_PATH}"
printf '  project: %s   spider: %s   version: %s\n' "${PROJECT}" "${SPIDER}" "${VERSION}"
printf '======================================================================\n'

# --- 1. clean-volume bring-up ----------------------------------------------
step "1. Clean-volume bring-up (down -v; up -d --build)"
dc down -v --remove-orphans >/dev/null 2>&1 || true
info "building dependency base images..."
"${REPO_ROOT}/scripts/build-docker-base.sh"
info "building + starting db, migrate, agent, server (this builds images)..."
dc up -d --build

# --- 2. wait for the stack --------------------------------------------------
step "2. Wait for services"
wait_healthy db "${HEALTH_TIMEOUT}"      && pass "db healthy"                || { fail "db did not become healthy"; dc logs db | tail -40 >&2; exit 1; }
wait_migrate "${HEALTH_TIMEOUT}"         && pass "migrate completed (alembic upgrade head from empty -> head)" || { fail "migrate did not complete successfully"; dc logs migrate | tail -60 >&2; exit 1; }
wait_healthy agent "${HEALTH_TIMEOUT}"   && pass "agent healthy"             || { fail "agent did not become healthy"; dc logs agent | tail -60 >&2; exit 1; }
wait_healthy server "${HEALTH_TIMEOUT}"  && pass "server healthy"            || { fail "server did not become healthy"; dc logs server | tail -60 >&2; exit 1; }

# --- 3. agent /health reports a live scrapyd subprocess ---------------------
step "3. Assert agent reports a live scrapyd subprocess"
AGENT_HEALTH="$(curl -fsS "${AGENT}/health" || true)"
SCRAPYD_RUNNING="$(json_get "${AGENT_HEALTH}" "detail.scrapyd.running")"
if [ "${SCRAPYD_RUNNING}" = "true" ]; then
  pass "agent /health detail.scrapyd.running == true"
else
  fail "agent /health did not report scrapyd running (got: ${AGENT_HEALTH})"
  dc logs agent | tail -60 >&2
  exit 1
fi

# --- 4. login (web auth is ON) ---------------------------------------------
step "4. Authenticate (web auth ON in server.docker.toml)"
TOKEN="$(login_token)"
if [ -z "${TOKEN}" ]; then
  fail "login returned no access_token (auth misconfigured?)"
  exit 1
fi
AUTH=(-H "Authorization: Bearer ${TOKEN}")
pass "obtained admin bearer token"

# --- 5. server sees a healthy agent ----------------------------------------
step "5. POST /api/v1/nodes/refresh -> healthy agent w/ scrapyd"
NODES="$(curl -fsS -X POST "${SERVER}/api/v1/nodes/refresh" "${AUTH[@]}" || true)"
NODE_STATUS="$(json_get "${NODES}" "nodes[0].status")"
NODE_SCRAPYD="$(json_get "${NODES}" "nodes[0].health.scrapyd.running")"
if [ "${NODE_STATUS}" = "healthy" ]; then
  pass "nodes[0].status == healthy"
else
  fail "no healthy agent after refresh (got status: ${NODE_STATUS}; body: ${NODES})"
  exit 1
fi
[ "${NODE_SCRAPYD}" = "true" ] && pass "nodes[0].health.scrapyd.running == true" \
  || info "node health did not surface scrapyd.running (non-fatal): ${NODES}"

# --- 6. ensure the demo egg exists (build in-container if missing) ----------
step "6. Resolve demo egg"
if [ -f "${EGG_PATH}" ]; then
  pass "committed egg present: ${EGG_PATH}"
else
  info "committed egg missing -> building it inside the agent container"
  # The fixture project is NOT mounted into the agent, so copy it in, build the
  # egg with setup.py bdist_egg (the agent image has scrapy + setuptools), and
  # copy the result back to the host EGG_PATH.
  AGENT_CID="$(dc ps -q agent)"
  docker cp "${REPO_ROOT}/tests/fixtures/scrapy_demo/." "${AGENT_CID}:/tmp/scrapy_demo"
  docker exec "${AGENT_CID}" sh -c 'cd /tmp/scrapy_demo && rm -rf build dist demo.egg-info && python3 setup.py bdist_egg && cp dist/*.egg /tmp/demo_phase1.egg'
  mkdir -p "$(dirname "${EGG_PATH}")"
  docker cp "${AGENT_CID}:/tmp/demo_phase1.egg" "${EGG_PATH}"
  [ -f "${EGG_PATH}" ] && pass "built egg in agent container -> ${EGG_PATH}" \
    || { fail "could not build demo egg in agent container"; exit 1; }
fi

# --- 7. upload the egg ------------------------------------------------------
step "7. POST /api/v1/artifacts/scrapy/egg (multipart)"
UPLOAD="$(curl -fsS -X POST "${SERVER}/api/v1/artifacts/scrapy/egg" "${AUTH[@]}" \
  -F "project=${PROJECT}" \
  -F "version=${VERSION}" \
  -F "file=@${EGG_PATH}" 2>/dev/null || true)"
ART_PROJECT="$(json_get "${UPLOAD}" "artifact.project")"
if [ "${ART_PROJECT}" = "${PROJECT}" ]; then
  pass "egg deployed (artifact.project == ${PROJECT})"
else
  fail "egg upload failed (response: ${UPLOAD})"
  dc logs agent | tail -40 >&2
  exit 1
fi

# --- 8. run the demo spider -------------------------------------------------
step "8. POST /api/v1/executions/run (scrapy demo:phase1, node_strategy=all)"
RUN="$(curl -fsS -X POST "${SERVER}/api/v1/executions/run" "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d "{\"task_type\":\"scrapy\",\"target\":\"${PROJECT}:${SPIDER}\",\"node_strategy\":\"all\",\"params\":{\"project\":\"${PROJECT}\",\"spider\":\"${SPIDER}\"}}" 2>/dev/null || true)"
EXEC_ID="$(json_get "${RUN}" "execution_id")"
[ -z "${EXEC_ID}" ] && EXEC_ID="$(json_get "${RUN}" "id")"
if [ -n "${EXEC_ID}" ]; then
  pass "execution created (id == ${EXEC_ID})"
else
  fail "executions/run returned no execution id (response: ${RUN})"
  exit 1
fi

# --- 9. poll to a terminal status -------------------------------------------
step "9. Poll GET /api/v1/executions/{id} until terminal"
DEADLINE=$(( $(date +%s) + EXEC_TIMEOUT ))
STATUS=""
while :; do
  DETAIL="$(curl -fsS "${SERVER}/api/v1/executions/${EXEC_ID}" "${AUTH[@]}" || true)"
  STATUS="$(json_get "${DETAIL}" "status")"
  case "${STATUS}" in
    complete|failed|canceled|lost) break ;;
  esac
  if [ "$(date +%s)" -ge "${DEADLINE}" ]; then
    fail "execution did not reach a terminal status within ${EXEC_TIMEOUT}s (last: ${STATUS:-<none>})"
    dc logs server | tail -60 >&2
    dc logs agent | tail -60 >&2
    exit 1
  fi
  sleep 2
done
info "terminal status: ${STATUS}"

# --- 10. assert the demo markers landed in server logs ----------------------
step "10. GET /api/v1/executions/{id}/logs -> assert demo markers"
LOGS="$(curl -fsS "${SERVER}/api/v1/executions/${EXEC_ID}/logs" "${AUTH[@]}" || true)"
LOG_CONTENT="$(json_get "${LOGS}" "content")"
if [ -z "${LOG_CONTENT}" ]; then
  # Some implementations return a list of slices; fall back to the raw body.
  LOG_CONTENT="${LOGS}"
fi
MISSING=0
for marker in "phase1 demo spider started" "phase1 demo spider done"; do
  if printf '%s' "${LOG_CONTENT}" | grep -qF "${marker}"; then
    pass "log marker present: '${marker}'"
  else
    fail "log marker MISSING: '${marker}'"
    MISSING=1
  fi
done
if [ "${MISSING}" -ne 0 ]; then
  info "server logs body (tail):"
  printf '%s\n' "${LOG_CONTENT}" | tail -40 >&2
  exit 1
fi

# --- 11. assert final status == complete ------------------------------------
step "11. Assert final execution status == complete"
if [ "${STATUS}" = "complete" ]; then
  pass "execution status == complete"
else
  fail "execution ended in '${STATUS}', expected 'complete'"
  exit 1
fi

# ---- summary ---------------------------------------------------------------
step "Smoke summary"
printf '  passed: %d   failed: %d\n' "${PASS_COUNT}" "${FAIL_COUNT}"
if [ "${FAIL_COUNT}" -ne 0 ]; then
  printf '\n\033[31mSMOKE FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[32mSMOKE PASSED\033[0m\n'
# Teardown happens in the EXIT trap (unless KEEP_UP=1).
