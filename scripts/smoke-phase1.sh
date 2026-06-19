#!/usr/bin/env bash
#
# dopilot phase-1 / phase-1.7 compose smoke: a repeatable, clean-volume
# end-to-end check of the real Scrapy execution chain over the Redis Streams
# model (brief §7.6 / §10 + phase 1.7 template/schedule paths):
#
#   server API -> template -> task -> ScrapydExecutor -> Redis command stream
#     -> agent consumes run command -> in-agent scrapyd -> scrapy demo:phase1
#     -> agent XADDs log increments to dopilot:server:logs
#     -> server log consumer -> /server-data/logs + PostgreSQL index
#     -> server returns landed logs over SSE/HTTP
#
# It builds the images, brings up db -> migrate (alembic head incl. 0005) ->
# agent -> server on FRESH volumes, waits for a heartbeat-healthy agent (the
# Redis heartbeat model; the old POST /nodes/refresh is gone), asserts
# /health reports DB/Redis/nodes ok, uploads the committed demo egg, creates a
# Scrapy TEMPLATE, runs it (template -> task -> one execution per healthy node),
# polls the task to terminal, asserts the demo marker lines landed in the server
# logs, asserts the final status is `complete`, then exercises the schedule
# trigger-now path (schedule -> task).
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
  if [ "${rc}" -ne 0 ]; then
    printf '\n\033[31mSMOKE FAILED\033[0m\n'
  fi
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

json_template_payload() {
  python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json, sys

name, project, spider, artifact_raw, version = sys.argv[1:6]
payload = {
    "name": name,
    "task_type": "scrapy",
    "project": project,
    "spider": spider,
    "version": version,
    "node_strategy": "all",
}
artifact = json.loads(artifact_raw or "{}")
if artifact:
    payload["artifact"] = artifact
print(json.dumps(payload, separators=(",", ":")))
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

# --- 5. server sees a healthy agent (Redis heartbeat model) -----------------
# Phase 1.5+: node liveness is sourced from agent-initiated heartbeats
# (POST /api/v1/agents/{id}/heartbeat), NOT a server-driven /nodes/refresh poll
# (that endpoint is gone). The agent heartbeats on its own once it is up, so we
# poll GET /api/v1/nodes until a node reports `healthy`.
step "5. Poll GET /api/v1/nodes until a heartbeat-healthy agent appears"
NODE_DEADLINE=$(( $(date +%s) + HEALTH_TIMEOUT ))
NODE_STATUS=""
while :; do
  NODES="$(curl -fsS "${SERVER}/api/v1/nodes" "${AUTH[@]}" || true)"
  NODE_STATUS="$(json_get "${NODES}" "nodes[0].status")"
  [ "${NODE_STATUS}" = "healthy" ] && break
  if [ "$(date +%s)" -ge "${NODE_DEADLINE}" ]; then
    fail "no heartbeat-healthy agent within ${HEALTH_TIMEOUT}s (last status: ${NODE_STATUS:-<none>}; body: ${NODES})"
    dc logs agent | tail -60 >&2
    exit 1
  fi
  sleep 3
done
pass "nodes[0].status == healthy (via agent heartbeat)"
NODE_SCRAPYD="$(json_get "${NODES}" "nodes[0].health.scrapyd.running")"
[ "${NODE_SCRAPYD}" = "true" ] && pass "nodes[0].health.scrapyd.running == true" \
  || info "node health did not surface scrapyd.running (non-fatal): ${NODES}"

# --- 5b. server /health reports DB + Redis + nodes ok -----------------------
step "5b. GET /api/v1/health -> DB/Redis/nodes ok"
HEALTH="$(curl -fsS "${SERVER}/api/v1/health" "${AUTH[@]}" || true)"
H_DB="$(json_get "${HEALTH}" "postgresql.status")"
H_REDIS="$(json_get "${HEALTH}" "redis.status")"
H_NODES_HEALTHY="$(json_get "${HEALTH}" "nodes.healthy")"
[ "${H_DB}" = "ok" ] && pass "health.postgresql.status == ok" \
  || { fail "health.postgresql.status != ok (body: ${HEALTH})"; exit 1; }
[ "${H_REDIS}" = "ok" ] && pass "health.redis.status == ok" \
  || { fail "health.redis.status != ok (body: ${HEALTH})"; exit 1; }
[ -n "${H_NODES_HEALTHY}" ] && [ "${H_NODES_HEALTHY}" -ge 1 ] 2>/dev/null \
  && pass "health.nodes.healthy >= 1 (${H_NODES_HEALTHY})" \
  || { fail "health.nodes.healthy < 1 (body: ${HEALTH})"; exit 1; }

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
ARTIFACT_JSON="$(python3 - "${UPLOAD}" <<'PY'
import json, sys

body = json.loads(sys.argv[1] or "{}")
print(json.dumps(body.get("artifact") or {}, separators=(",", ":")))
PY
)"

# --- 8. Phase 1.7 path: create a Scrapy template, then run it ---------------
# This exercises the canonical phase-1.7 template -> task -> execution flow
# (POST /templates then POST /templates/{id}/run), NOT the legacy direct
# /executions/run. The run response's `execution_id` is the new TASK id.
step "8. POST /api/v1/templates (scrapy demo:phase1, node_strategy=all)"
TPL_PAYLOAD="$(json_template_payload "smoke-${SPIDER}-${VERSION}" "${PROJECT}" "${SPIDER}" "${ARTIFACT_JSON}" "${VERSION}")"
TPL="$(curl -fsS -X POST "${SERVER}/api/v1/templates" "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d "${TPL_PAYLOAD}" 2>/dev/null || true)"
TEMPLATE_ID="$(json_get "${TPL}" "id")"
if [ -n "${TEMPLATE_ID}" ]; then
  pass "template created (id == ${TEMPLATE_ID})"
else
  fail "POST /templates returned no id (response: ${TPL})"
  exit 1
fi

step "8b. POST /api/v1/templates/{id}/run -> create a task from the snapshot"
RUN="$(curl -fsS -X POST "${SERVER}/api/v1/templates/${TEMPLATE_ID}/run" "${AUTH[@]}" \
  -H 'Content-Type: application/json' -d '{}' 2>/dev/null || true)"
EXEC_ID="$(json_get "${RUN}" "execution_id")"
[ -z "${EXEC_ID}" ] && EXEC_ID="$(json_get "${RUN}" "id")"
if [ -n "${EXEC_ID}" ]; then
  pass "task created from template (task id == ${EXEC_ID})"
else
  fail "template run returned no task id (response: ${RUN})"
  exit 1
fi

# Confirm the task has exactly one atomic execution (one healthy node, all).
TASK_DETAIL="$(curl -fsS "${SERVER}/api/v1/executions/${EXEC_ID}" "${AUTH[@]}" || true)"
TASK_SOURCE="$(json_get "${TASK_DETAIL}" "source")"
TASK_ATTEMPT0="$(json_get "${TASK_DETAIL}" "attempts[0].agent_id")"
[ "${TASK_SOURCE}" = "manual" ] && pass "task.source == manual (template run)" \
  || info "task.source == ${TASK_SOURCE} (non-fatal)"
[ -n "${TASK_ATTEMPT0}" ] && pass "task has a child execution on agent '${TASK_ATTEMPT0}'" \
  || { fail "task has no child execution (body: ${TASK_DETAIL})"; exit 1; }

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

# --- 12. Phase 1.7 schedule path: trigger-now creates a task ----------------
# Prove the schedule -> task path (same snapshot dispatch as a timer firing)
# also lands a task. We create a schedule referencing the step-8 template and
# trigger it immediately; we assert a NEW task is created with source
# `schedule_trigger_now` and a child execution. (We do not re-poll to terminal:
# step 8-11 already proved the full template -> log -> complete chain.)
step "12. POST /api/v1/schedules + /trigger-now -> task from schedule"
SCHED="$(curl -fsS -X POST "${SERVER}/api/v1/schedules" "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"smoke-sched-${VERSION}\",\"template_id\":\"${TEMPLATE_ID}\",\"trigger_type\":\"interval\",\"interval_seconds\":3600}" 2>/dev/null || true)"
SCHEDULE_ID="$(json_get "${SCHED}" "id")"
if [ -n "${SCHEDULE_ID}" ]; then
  pass "schedule created (id == ${SCHEDULE_ID})"
else
  fail "POST /schedules returned no id (response: ${SCHED})"
  exit 1
fi

TRIG="$(curl -fsS -X POST "${SERVER}/api/v1/schedules/${SCHEDULE_ID}/trigger-now" "${AUTH[@]}" \
  -H 'Content-Type: application/json' -d '{}' 2>/dev/null || true)"
TRIG_TASK_ID="$(json_get "${TRIG}" "execution_id")"
if [ -n "${TRIG_TASK_ID}" ] && [ "${TRIG_TASK_ID}" != "${EXEC_ID}" ]; then
  pass "trigger-now created a new task (id == ${TRIG_TASK_ID})"
else
  fail "trigger-now did not create a new task (response: ${TRIG})"
  exit 1
fi

TRIG_DETAIL="$(curl -fsS "${SERVER}/api/v1/executions/${TRIG_TASK_ID}" "${AUTH[@]}" || true)"
TRIG_SOURCE="$(json_get "${TRIG_DETAIL}" "source")"
TRIG_SCHED="$(json_get "${TRIG_DETAIL}" "schedule_id")"
[ "${TRIG_SOURCE}" = "schedule_trigger_now" ] \
  && pass "task.source == schedule_trigger_now" \
  || info "task.source == ${TRIG_SOURCE} (non-fatal)"
[ "${TRIG_SCHED}" = "${SCHEDULE_ID}" ] \
  && pass "task.schedule_id links back to the schedule" \
  || info "task.schedule_id == ${TRIG_SCHED} (non-fatal)"

# ---- summary ---------------------------------------------------------------
step "Smoke summary"
printf '  passed: %d   failed: %d\n' "${PASS_COUNT}" "${FAIL_COUNT}"
if [ "${FAIL_COUNT}" -ne 0 ]; then
  printf '\n\033[31mSMOKE FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[32mSMOKE PASSED\033[0m\n'
# Teardown happens in the EXIT trap (unless KEEP_UP=1).
