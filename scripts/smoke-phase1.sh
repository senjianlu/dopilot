#!/usr/bin/env bash
#
# dopilot Phase 1.8 full Docker E2E acceptance smoke.
#
# A repeatable, clean-volume end-to-end check of the clean-cut Phase 1.8 model
# running in the real deployed architecture with THREE real Scrapy agents:
#
#   PostgreSQL + Redis Streams + migrate + server + scrapy-agent-{1,2,3}
#
# Each agent owns its own scrapyd subprocess. The smoke proves the Phase 1.8
# PUBLIC vocabulary end to end:
#
#   * build artifact upload  -> POST /api/v1/artifacts/scrapy/egg (BuildArtifactView)
#   * execution template     -> POST /api/v1/templates (build_artifact_id bound)
#   * template run -> TASK    -> POST /api/v1/templates/{id}/run -> {task_id}
#   * parent task detail      -> GET  /api/v1/tasks/{task_id} (executions[], NOT attempts[])
#   * per-execution logs      -> GET  /api/v1/tasks/{task_id}/logs?execution_id=...
#   * schedule trigger-now    -> POST /api/v1/schedules/{id}/trigger-now (source=schedule_trigger_now)
#   * node-state -> dispatch  -> offline / heartbeat-timeout / soft-delete exclusion
#
# The key acceptance fact: node_strategy="all" over three healthy Scrapy-capable
# agents creates EXACTLY THREE atomic executions under one task, with three
# distinct agent ids, and each execution's own log carries the demo markers.
#
# This script HARD-FAILS if it ever depends on the OLD public vocabulary
# (/api/v1/executions, attempts[], an execution_id run response, or template_id).
#
# Usage:
#   scripts/smoke-phase1.sh            # full clean-volume E2E acceptance
#   KEEP_UP=1 scripts/smoke-phase1.sh  # leave the stack up on success (debug)
#
# Idempotent: always starts from `docker compose down -v` and always tears down
# on exit unless KEEP_UP=1 and the run passed.
#
# Requires: docker + docker compose v2, curl, python3 (all on the HOST). No
# python venv is needed — JSON is parsed with the host python3.

set -euo pipefail

# ---- locations -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/deploy/docker"
COMPOSE_BASE="${COMPOSE_DIR}/docker-compose.yml"
COMPOSE_E2E="${COMPOSE_DIR}/docker-compose.e2e.yml"
SERVER_CONFIG="${REPO_ROOT}/configs/server.docker.toml"
EGG_PATH="${REPO_ROOT}/tests/fixtures/scrapy_demo/eggs/demo_phase1.egg"

# Demo project/spider are fixed phase-1 constants (see fixture README).
PROJECT="demo"
SPIDER="phase1"
VERSION="$(date +%s)"          # monotonic-ish egg version for this run

# Demo spider marker lines (logged via self.logger.info; see the fixture spider).
MARKER_START="phase1 demo spider started"
MARKER_DONE="phase1 demo spider done"

# Host-facing service URLs (compose publishes these ports).
SERVER="http://localhost:5000"
AGENT1="http://localhost:6800"   # only scrapy-agent-1 publishes its HTTP port

# The three agents. agent_id -> compose service key. scrapy-agent-1 is the base
# `agent` service; -2 and -3 come from docker-compose.e2e.yml.
AGENT_IDS=(scrapy-agent-1 scrapy-agent-2 scrapy-agent-3)
declare -A SERVICE_OF=(
  [scrapy-agent-1]=agent
  [scrapy-agent-2]=scrapy-agent-2
  [scrapy-agent-3]=scrapy-agent-3
)

# Admin creds match configs/server.docker.toml ([auth] is set -> web auth ON).
ADMIN_USER="admin"
ADMIN_PASS="change-me"

# Timeouts (seconds).
HEALTH_TIMEOUT=240           # per service_healthy wait (3 agents + image build)
EXEC_TIMEOUT=180             # task run -> terminal status
LOG_TIMEOUT=45               # per-execution log markers to land

# Heartbeat timeout is read from the server config so the stop/unhealthy check
# uses the real configured window plus a clear margin (never a fixed short sleep).
HEARTBEAT_TIMEOUT="$(python3 - "${SERVER_CONFIG}" <<'PY'
import sys, tomllib
data = tomllib.load(open(sys.argv[1], "rb"))
print(int((data.get("agents") or {}).get("heartbeat_timeout_seconds", 30)))
PY
)"

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

dc() { docker compose -f "${COMPOSE_BASE}" -f "${COMPOSE_E2E}" "$@"; }

# ---- diagnostics dump (on any compose-smoke failure) -----------------------
dump_diagnostics() {
  local why="$1"
  printf '\n\033[31m==== SMOKE DIAGNOSTICS (%s) ====\033[0m\n' "${why}" >&2
  printf '\n-- docker compose ps --\n' >&2
  dc ps >&2 2>&1 || true
  printf '\n-- server logs (tail 80) --\n' >&2
  dc logs --tail 80 server >&2 2>&1 || true
  printf '\n-- redis logs (tail 30) --\n' >&2
  dc logs --tail 30 redis >&2 2>&1 || true
  for aid in "${AGENT_IDS[@]}"; do
    printf '\n-- %s (%s) logs (tail 60) --\n' "${aid}" "${SERVICE_OF[$aid]}" >&2
    dc logs --tail 60 "${SERVICE_OF[$aid]}" >&2 2>&1 || true
  done
}

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

# ===========================================================================
# python JSON helpers (host python3; no venv required)
# ===========================================================================

# json_get '<json>' '<dotted.path>'  -> prints the scalar value or empty string.
# Supports dotted keys and [n] list indices, e.g. executions[0].agent_id.
json_get() {
  python3 - "$1" "$2" <<'PY'
import json, sys, re
data = json.loads(sys.argv[1] or "{}")
cur = data
for part in re.findall(r'[^.\[\]]+|\[\d+\]', sys.argv[2]):
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

# has_key '<json>' '<top-level-key>' -> prints "true" if the key exists.
has_key() {
  python3 - "$1" "$2" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
print("true" if isinstance(data, dict) and sys.argv[2] in data else "false")
PY
}

# node_rows '<nodes_json>' -> one TAB row per PERSISTED node (id != null):
#   agent_id <TAB> node_id <TAB> status <TAB> scrapy(true|false) <TAB>
#   scheduling_enabled(true|false) <TAB> deleted(yes|no)
node_rows() {
  python3 - "$1" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
for n in data.get("nodes", []):
    if not n.get("id"):
        continue  # configured-but-unseen phantom (no DB row) -> not persisted
    caps = n.get("capabilities") or {}
    print("\t".join([
        str(n.get("agent_id") or ""),
        str(n.get("id") or ""),
        str(n.get("status") or ""),
        "true" if caps.get("scrapy") else "false",
        "true" if n.get("scheduling_enabled") else "false",
        "yes" if n.get("deleted_at") else "no",
    ]))
PY
}

# exec_rows '<task_json>' -> one TAB row per atomic execution:
#   execution_id <TAB> agent_id <TAB> status
exec_rows() {
  python3 - "$1" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
for e in data.get("executions", []):
    print("\t".join([
        str(e.get("id") or ""),
        str(e.get("agent_id") or ""),
        str(e.get("status") or ""),
    ]))
PY
}

# ---- node-state cache ------------------------------------------------------
declare -A NODE_ID NODE_STATUS NODE_SCRAPY NODE_SCHED NODE_DELETED
NODES_JSON=""
PERSISTED_COUNT=0

refresh_nodes() {
  NODES_JSON="$(curl -fsS "${SERVER}/api/v1/nodes" "${AUTH[@]}" || true)"
  NODE_ID=(); NODE_STATUS=(); NODE_SCRAPY=(); NODE_SCHED=(); NODE_DELETED=()
  local aid nid st scr sch del
  while IFS=$'\t' read -r aid nid st scr sch del; do
    [ -z "${aid}" ] && continue
    NODE_ID[$aid]="${nid}"
    NODE_STATUS[$aid]="${st}"
    NODE_SCRAPY[$aid]="${scr}"
    NODE_SCHED[$aid]="${sch}"
    NODE_DELETED[$aid]="${del}"
  done < <(node_rows "${NODES_JSON}")
  PERSISTED_COUNT=${#NODE_ID[@]}
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
      [ "${health}" = "healthy" ] && return 0
      [ "${state}" = "exited" ] && return 1
    fi
    [ "$(date +%s)" -ge "${deadline}" ] && return 1
    sleep 3
  done
}

# wait_migrate <timeout-seconds>: the migrate service is one-shot; success = 0.
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

# ---- auth ------------------------------------------------------------------
login_token() {
  local resp
  resp="$(curl -fsS -X POST "${SERVER}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" 2>/dev/null || true)"
  json_get "${resp}" "access_token"
}

# ---- task helpers ----------------------------------------------------------
TASK_BODY=""
TASK_STATUS=""

# wait_task <task_id> <timeout> -> polls GET /tasks/{id} to a terminal status,
# leaving the final body in TASK_BODY and status in TASK_STATUS.
wait_task() {
  local tid="$1" timeout="$2" deadline body status
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    body="$(curl -fsS "${SERVER}/api/v1/tasks/${tid}" "${AUTH[@]}" || true)"
    status="$(json_get "${body}" "status")"
    case "${status}" in
      complete|failed|canceled|lost|no_target) break ;;
    esac
    [ "$(date +%s)" -ge "${deadline}" ] && break
    sleep 2
  done
  TASK_BODY="${body}"
  TASK_STATUS="${status}"
}

# run_template_task -> runs the shared TEMPLATE_ID, echoes the new task_id.
run_template_task() {
  local run
  run="$(curl -fsS -X POST "${SERVER}/api/v1/templates/${TEMPLATE_ID}/run" \
    "${AUTH[@]}" -H 'Content-Type: application/json' 2>/dev/null || true)"
  json_get "${run}" "task_id"
}

# assert_exec_logs <task_id> <execution_id> <agent_id>: per-execution log must
# carry BOTH demo markers (proves THAT agent actually ran the spider).
assert_exec_logs() {
  local tid="$1" eid="$2" aid="$3" deadline logs content
  deadline=$(( $(date +%s) + LOG_TIMEOUT ))
  while :; do
    logs="$(curl -fsS "${SERVER}/api/v1/tasks/${tid}/logs?execution_id=${eid}&stream=log" \
      "${AUTH[@]}" || true)"
    content="$(json_get "${logs}" "content")"
    if printf '%s' "${content}" | grep -qF "${MARKER_START}" \
       && printf '%s' "${content}" | grep -qF "${MARKER_DONE}"; then
      pass "execution ${aid} log has both demo markers"
      return 0
    fi
    [ "$(date +%s)" -ge "${deadline}" ] && break
    sleep 2
  done
  fail "execution ${aid} (${eid}) log missing demo markers within ${LOG_TIMEOUT}s"
  info "last log body (tail):"
  printf '%s\n' "${content}" | tail -20 >&2
  return 1
}

# =============================================================================
# Run
# =============================================================================
printf '======================================================================\n'
printf 'dopilot Phase 1.8 E2E acceptance smoke (three real agents)\n'
printf '  repo:      %s\n' "${REPO_ROOT}"
printf '  egg:       %s\n' "${EGG_PATH}"
printf '  agents:    %s\n' "${AGENT_IDS[*]}"
printf '  heartbeat: %ss timeout\n' "${HEARTBEAT_TIMEOUT}"
printf '  project:   %s   spider: %s   version: %s\n' "${PROJECT}" "${SPIDER}" "${VERSION}"
printf '======================================================================\n'

# --- Case 1: clean-volume bring-up -----------------------------------------
step "Case 1. Clean-volume bring-up (down -v; up -d --build) — 3 agents"
dc down -v --remove-orphans >/dev/null 2>&1 || true
info "building dependency base images..."
"${REPO_ROOT}/scripts/build-docker-base.sh"
info "building + starting db, redis, migrate, server, and 3 agents..."
dc up -d --build

step "Case 1. Wait for services (db, migrate, 3 agents, server)"
wait_healthy db "${HEALTH_TIMEOUT}"       && pass "db healthy" \
  || { fail "db did not become healthy"; dump_diagnostics "db unhealthy"; exit 1; }
wait_migrate "${HEALTH_TIMEOUT}"          && pass "migrate completed (alembic upgrade head)" \
  || { fail "migrate did not complete"; dc logs migrate | tail -60 >&2; exit 1; }
for aid in "${AGENT_IDS[@]}"; do
  svc="${SERVICE_OF[$aid]}"
  wait_healthy "${svc}" "${HEALTH_TIMEOUT}" && pass "${aid} container healthy" \
    || { fail "${aid} (${svc}) did not become healthy"; dump_diagnostics "${aid} unhealthy"; exit 1; }
done
wait_healthy server "${HEALTH_TIMEOUT}"   && pass "server healthy" \
  || { fail "server did not become healthy"; dump_diagnostics "server unhealthy"; exit 1; }

# Direct scrapyd-liveness probe for the one published agent (scrapy-agent-1).
A1_HEALTH="$(curl -fsS "${AGENT1}/health" || true)"
[ "$(json_get "${A1_HEALTH}" "detail.scrapyd.running")" = "true" ] \
  && pass "scrapy-agent-1 /health detail.scrapyd.running == true" \
  || { fail "scrapy-agent-1 scrapyd not running (got: ${A1_HEALTH})"; dump_diagnostics "scrapyd-1 down"; exit 1; }

# --- login (web auth ON) ----------------------------------------------------
step "Authenticate (web auth ON in server.docker.toml)"
TOKEN="$(login_token)"
[ -n "${TOKEN}" ] || { fail "login returned no access_token"; exit 1; }
AUTH=(-H "Authorization: Bearer ${TOKEN}")
pass "obtained admin bearer token"

# --- Case 2: three heartbeat-healthy, Scrapy-capable, schedulable nodes ------
step "Case 2. Poll GET /api/v1/nodes for exactly 3 healthy schedulable nodes"
NODE_DEADLINE=$(( $(date +%s) + HEALTH_TIMEOUT ))
while :; do
  refresh_nodes
  ready=0
  if [ "${PERSISTED_COUNT}" -eq 3 ]; then
    ready=1
    for aid in "${AGENT_IDS[@]}"; do
      [ "${NODE_STATUS[$aid]:-}" = "healthy" ] \
        && [ "${NODE_SCRAPY[$aid]:-}" = "true" ] \
        && [ "${NODE_SCHED[$aid]:-}" = "true" ] || ready=0
    done
  fi
  [ "${ready}" -eq 1 ] && break
  if [ "$(date +%s)" -ge "${NODE_DEADLINE}" ]; then
    fail "did not reach 3 healthy schedulable nodes (persisted=${PERSISTED_COUNT}; body: ${NODES_JSON})"
    dump_diagnostics "nodes not healthy"
    exit 1
  fi
  sleep 3
done
pass "exactly 3 persisted nodes (no phantom configured rows)"
for aid in "${AGENT_IDS[@]}"; do
  pass "node ${aid}: status=healthy, capabilities.scrapy=true, scheduling_enabled=true"
done

# --- Case 2b: server /health reports DB + Redis + nodes.healthy == 3 ---------
step "Case 2b. GET /api/v1/health -> DB/Redis ok, nodes.healthy == 3"
HEALTH="$(curl -fsS "${SERVER}/api/v1/health" "${AUTH[@]}" || true)"
[ "$(json_get "${HEALTH}" "postgresql.status")" = "ok" ] && pass "health.postgresql.status == ok" \
  || { fail "postgresql not ok (body: ${HEALTH})"; exit 1; }
[ "$(json_get "${HEALTH}" "redis.status")" = "ok" ] && pass "health.redis.status == ok" \
  || { fail "redis not ok (body: ${HEALTH})"; exit 1; }
[ "$(json_get "${HEALTH}" "nodes.healthy")" = "3" ] && pass "health.nodes.healthy == 3" \
  || { fail "health.nodes.healthy != 3 (body: ${HEALTH})"; exit 1; }

# --- Case 3: build artifact upload ------------------------------------------
step "Case 3. Resolve demo egg (build inside scrapy-agent-1 if missing)"
if [ -f "${EGG_PATH}" ]; then
  pass "committed egg present: ${EGG_PATH}"
else
  info "committed egg missing -> building it inside the scrapy-agent-1 container"
  A1_CID="$(dc ps -q agent)"
  docker cp "${REPO_ROOT}/tests/fixtures/scrapy_demo/." "${A1_CID}:/tmp/scrapy_demo"
  docker exec "${A1_CID}" sh -c 'cd /tmp/scrapy_demo && rm -rf build dist demo.egg-info && python3 setup.py bdist_egg && cp dist/*.egg /tmp/demo_phase1.egg'
  mkdir -p "$(dirname "${EGG_PATH}")"
  docker cp "${A1_CID}:/tmp/demo_phase1.egg" "${EGG_PATH}"
  [ -f "${EGG_PATH}" ] && pass "built egg in agent container -> ${EGG_PATH}" \
    || { fail "could not build demo egg in agent container"; exit 1; }
fi

step "Case 3. POST /api/v1/artifacts/scrapy/egg -> BuildArtifactView"
UPLOAD="$(curl -fsS -X POST "${SERVER}/api/v1/artifacts/scrapy/egg" "${AUTH[@]}" \
  -F "project=${PROJECT}" -F "version=${VERSION}" -F "file=@${EGG_PATH}" 2>/dev/null || true)"
ARTIFACT_ID="$(json_get "${UPLOAD}" "artifact.id")"
ART_TYPE="$(json_get "${UPLOAD}" "artifact.artifact_type")"
ART_FORMAT="$(json_get "${UPLOAD}" "artifact.package_format")"
[ -n "${ARTIFACT_ID}" ] && pass "upload returned artifact.id (${ARTIFACT_ID})" \
  || { fail "upload returned no artifact id (response: ${UPLOAD})"; dump_diagnostics "egg upload"; exit 1; }
[ "${ART_TYPE}" = "scrapy" ] && pass "artifact.artifact_type == scrapy" \
  || { fail "artifact_type != scrapy (got: ${ART_TYPE})"; exit 1; }
[ "${ART_FORMAT}" = "egg" ] && pass "artifact.package_format == egg" \
  || { fail "package_format != egg (got: ${ART_FORMAT})"; exit 1; }

ART_LIST="$(curl -fsS "${SERVER}/api/v1/artifacts" "${AUTH[@]}" || true)"
if python3 - "${ART_LIST}" "${ARTIFACT_ID}" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
sys.exit(0 if any(a.get("id") == sys.argv[2] for a in data.get("artifacts", [])) else 1)
PY
then pass "GET /api/v1/artifacts lists the uploaded artifact"
else fail "artifact ${ARTIFACT_ID} not in /api/v1/artifacts (body: ${ART_LIST})"; exit 1; fi

# --- Case 4: template run fans out to THREE agents --------------------------
step "Case 4. POST /api/v1/templates (build_artifact_id, spider=${SPIDER}, node_strategy=all)"
# Command-first (phase 1.8.1): the template carries a `scrapy crawl ...` command.
# Pass `-a duration_seconds=0` (phase 1.8.2) so the demo spider stays near-instant
# instead of waiting for its new 60-second default.
TPL_PAYLOAD="$(python3 - "smoke-${SPIDER}-${VERSION}" "${ARTIFACT_ID}" "${SPIDER}" <<'PY'
import json, sys
print(json.dumps({
    "name": sys.argv[1],
    "build_artifact_id": sys.argv[2],
    "command": f"scrapy crawl {sys.argv[3]} -a duration_seconds=0",
    "node_strategy": "all",
}, separators=(",", ":")))
PY
)"
TPL="$(curl -fsS -X POST "${SERVER}/api/v1/templates" "${AUTH[@]}" \
  -H 'Content-Type: application/json' -d "${TPL_PAYLOAD}" 2>/dev/null || true)"
TEMPLATE_ID="$(json_get "${TPL}" "id")"
TPL_ARTIFACT="$(json_get "${TPL}" "build_artifact_id")"
[ -n "${TEMPLATE_ID}" ] && pass "template created (id=${TEMPLATE_ID})" \
  || { fail "POST /templates returned no id (response: ${TPL})"; exit 1; }
[ "${TPL_ARTIFACT}" = "${ARTIFACT_ID}" ] && pass "template bound build_artifact_id == ${ARTIFACT_ID}" \
  || { fail "template build_artifact_id mismatch (got: ${TPL_ARTIFACT})"; exit 1; }

step "Case 4. POST /api/v1/templates/{id}/run -> task_id (NOT execution_id)"
RUN="$(curl -fsS -X POST "${SERVER}/api/v1/templates/${TEMPLATE_ID}/run" "${AUTH[@]}" \
  -H 'Content-Type: application/json' 2>/dev/null || true)"
TASK_ID="$(json_get "${RUN}" "task_id")"
[ -n "${TASK_ID}" ] && pass "template run returned task_id (${TASK_ID})" \
  || { fail "template run returned no task_id (response: ${RUN})"; exit 1; }
# Regression guard: the OLD vocabulary must be gone.
[ "$(has_key "${RUN}" "execution_id")" = "false" ] && pass "run response has NO execution_id (clean-cut)" \
  || { fail "run response still exposes execution_id (regression): ${RUN}"; exit 1; }

step "Case 4. GET /api/v1/tasks/{task_id} -> executions[] (NOT attempts[]), source=template"
TASK="$(curl -fsS "${SERVER}/api/v1/tasks/${TASK_ID}" "${AUTH[@]}" || true)"
[ "$(has_key "${TASK}" "executions")" = "true" ] && pass "task detail has executions[]" \
  || { fail "task detail has no executions[] (body: ${TASK})"; exit 1; }
[ "$(has_key "${TASK}" "attempts")" = "false" ] && pass "task detail has NO attempts[] (clean-cut)" \
  || { fail "task detail still exposes attempts[] (regression): ${TASK}"; exit 1; }
[ "$(json_get "${TASK}" "source")" = "template" ] && pass "task.source == template" \
  || { fail "task.source != template (got: $(json_get "${TASK}" source))"; exit 1; }

step "Case 4. Poll task to terminal + assert 3 distinct-agent executions"
wait_task "${TASK_ID}" "${EXEC_TIMEOUT}"
[ "${TASK_STATUS}" = "complete" ] && pass "task status == complete" \
  || { fail "task ended '${TASK_STATUS}', expected complete"; dump_diagnostics "task not complete"; exit 1; }
EXEC_COUNT="$(exec_rows "${TASK_BODY}" | grep -c . || true)"
[ "${EXEC_COUNT}" = "3" ] && pass "task has EXACTLY 3 executions" \
  || { fail "expected 3 executions, got ${EXEC_COUNT} (body: ${TASK_BODY})"; exit 1; }
EXEC_AGENTS="$(exec_rows "${TASK_BODY}" | cut -f2 | sort -u | tr '\n' ' ' | sed 's/ $//')"
EXPECT_AGENTS="$(printf '%s\n' "${AGENT_IDS[@]}" | sort | tr '\n' ' ' | sed 's/ $//')"
[ "${EXEC_AGENTS}" = "${EXPECT_AGENTS}" ] && pass "3 distinct agent ids == heartbeat agents (${EXEC_AGENTS})" \
  || { fail "execution agent ids '${EXEC_AGENTS}' != heartbeat agents '${EXPECT_AGENTS}'"; exit 1; }

step "Case 4. Per-execution logs: each child execution carries the demo markers"
while IFS=$'\t' read -r eid aid est; do
  [ -z "${eid}" ] && continue
  [ "${est}" = "finished" ] && pass "execution ${aid} status == finished" \
    || info "execution ${aid} status == ${est}"
  assert_exec_logs "${TASK_ID}" "${eid}" "${aid}" || exit 1
done < <(exec_rows "${TASK_BODY}")

# --- Case 5: schedule trigger-now -------------------------------------------
step "Case 5. POST /api/v1/schedules (execution_template_id) + /trigger-now"
SCHED="$(curl -fsS -X POST "${SERVER}/api/v1/schedules" "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"smoke-sched-${VERSION}\",\"execution_template_id\":\"${TEMPLATE_ID}\",\"trigger_type\":\"interval\",\"interval_seconds\":3600}" 2>/dev/null || true)"
SCHEDULE_ID="$(json_get "${SCHED}" "id")"
SCHED_TPL="$(json_get "${SCHED}" "execution_template_id")"
[ -n "${SCHEDULE_ID}" ] && pass "schedule created (id=${SCHEDULE_ID})" \
  || { fail "POST /schedules returned no id (response: ${SCHED})"; exit 1; }
[ "${SCHED_TPL}" = "${TEMPLATE_ID}" ] && pass "schedule.execution_template_id links the template" \
  || { fail "schedule.execution_template_id mismatch (got: ${SCHED_TPL})"; exit 1; }

TRIG="$(curl -fsS -X POST "${SERVER}/api/v1/schedules/${SCHEDULE_ID}/trigger-now" "${AUTH[@]}" \
  -H 'Content-Type: application/json' 2>/dev/null || true)"
TRIG_TASK_ID="$(json_get "${TRIG}" "task_id")"
[ -n "${TRIG_TASK_ID}" ] && [ "${TRIG_TASK_ID}" != "${TASK_ID}" ] \
  && pass "trigger-now created a new task (id=${TRIG_TASK_ID})" \
  || { fail "trigger-now did not create a new task (response: ${TRIG})"; exit 1; }
TRIG_DETAIL="$(curl -fsS "${SERVER}/api/v1/tasks/${TRIG_TASK_ID}" "${AUTH[@]}" || true)"
[ "$(json_get "${TRIG_DETAIL}" "source")" = "schedule_trigger_now" ] \
  && pass "task.source == schedule_trigger_now" \
  || { fail "trigger task.source != schedule_trigger_now (got: $(json_get "${TRIG_DETAIL}" source))"; exit 1; }
[ "$(json_get "${TRIG_DETAIL}" "schedule_id")" = "${SCHEDULE_ID}" ] \
  && pass "task.schedule_id links back to the schedule" \
  || { fail "task.schedule_id != ${SCHEDULE_ID} (got: $(json_get "${TRIG_DETAIL}" schedule_id))"; exit 1; }
[ "$(exec_rows "${TRIG_DETAIL}" | grep -c . || true)" -ge 1 ] 2>/dev/null \
  && pass "schedule task has child executions" \
  || info "schedule task has no executions yet (non-fatal; dispatch is async)"

# --- Case 6: offline node exclusion -----------------------------------------
# Take scrapy-agent-3 OFFLINE (reversible). Its container keeps heartbeating, so
# it stays heartbeat-healthy, but scheduling_enabled=false excludes it from
# dispatch. An all-nodes run must then create exactly TWO executions.
OFFLINE_AID="scrapy-agent-3"
step "Case 6. POST /api/v1/nodes/{id}/offline (${OFFLINE_AID}) -> excluded from dispatch"
OFFLINE_NODE_ID="${NODE_ID[$OFFLINE_AID]}"
OFF="$(curl -fsS -X POST "${SERVER}/api/v1/nodes/${OFFLINE_NODE_ID}/offline" "${AUTH[@]}" || true)"
[ "$(json_get "${OFF}" "scheduling_enabled")" = "false" ] && pass "${OFFLINE_AID} scheduling_enabled == false" \
  || { fail "offline did not disable scheduling (body: ${OFF})"; exit 1; }
refresh_nodes
[ "${NODE_STATUS[$OFFLINE_AID]:-}" = "healthy" ] && pass "${OFFLINE_AID} still heartbeat-healthy while offline" \
  || info "${OFFLINE_AID} status == ${NODE_STATUS[$OFFLINE_AID]:-} (heartbeat may lag; non-fatal)"

step "Case 6. All-nodes run excludes the offline node -> exactly 2 executions"
T7="$(run_template_task)"
[ -n "${T7}" ] || { fail "case-7 template run returned no task_id"; exit 1; }
wait_task "${T7}" "${EXEC_TIMEOUT}"
C7="$(exec_rows "${TASK_BODY}" | grep -c . || true)"
[ "${C7}" = "2" ] && pass "offline run created exactly 2 executions" \
  || { fail "expected 2 executions after offline, got ${C7} (body: ${TASK_BODY})"; exit 1; }
if exec_rows "${TASK_BODY}" | cut -f2 | grep -qx "${OFFLINE_AID}"; then
  fail "offline node ${OFFLINE_AID} was still selected"; exit 1
else
  pass "offline node ${OFFLINE_AID} was NOT selected"
fi

# --- Case 7: heartbeat-timeout exclusion ------------------------------------
# Stop scrapy-agent-2's container. After heartbeat_timeout + margin it goes
# unhealthy and is excluded. Only scrapy-agent-1 remains healthy+schedulable.
STOP_AID="scrapy-agent-2"
step "Case 7. Stop ${STOP_AID} container; wait past heartbeat timeout (${HEARTBEAT_TIMEOUT}s)"
dc stop "${SERVICE_OF[$STOP_AID]}" >/dev/null 2>&1 || true
pass "${STOP_AID} container stopped"
UNHEALTHY_DEADLINE=$(( $(date +%s) + HEARTBEAT_TIMEOUT + 90 ))
while :; do
  refresh_nodes
  [ "${NODE_STATUS[$STOP_AID]:-}" != "healthy" ] && break
  if [ "$(date +%s)" -ge "${UNHEALTHY_DEADLINE}" ]; then
    fail "${STOP_AID} still healthy after heartbeat timeout + margin (status: ${NODE_STATUS[$STOP_AID]:-})"
    dump_diagnostics "stop node still healthy"; exit 1
  fi
  sleep 3
done
pass "${STOP_AID} became '${NODE_STATUS[$STOP_AID]:-}' (not healthy) after heartbeat timeout"

step "Case 7. All-nodes run excludes the stopped node -> exactly 1 execution"
T8="$(run_template_task)"
[ -n "${T8}" ] || { fail "case-8 template run returned no task_id"; exit 1; }
wait_task "${T8}" "${EXEC_TIMEOUT}"
C8="$(exec_rows "${TASK_BODY}" | grep -c . || true)"
[ "${C8}" = "1" ] && pass "stopped+offline excluded: exactly 1 execution remains" \
  || { fail "expected 1 execution (only scrapy-agent-1 healthy+schedulable), got ${C8} (body: ${TASK_BODY})"; exit 1; }
if exec_rows "${TASK_BODY}" | cut -f2 | grep -qx "${STOP_AID}"; then
  fail "stopped node ${STOP_AID} was still selected"; exit 1
else
  pass "stopped node ${STOP_AID} was NOT selected"
fi

# --- Case 8: soft-delete exclusion ------------------------------------------
# Soft-delete scrapy-agent-3 (still running + heartbeating). deleted_at is set;
# a later heartbeat must NOT clear it, and it must stay excluded from dispatch.
DEL_AID="scrapy-agent-3"
step "Case 8. DELETE /api/v1/nodes/{id} (${DEL_AID}) -> soft-delete"
DEL_NODE_ID="${NODE_ID[$DEL_AID]}"
DEL="$(curl -fsS -X DELETE "${SERVER}/api/v1/nodes/${DEL_NODE_ID}" "${AUTH[@]}" || true)"
[ -n "$(json_get "${DEL}" "deleted_at")" ] && pass "${DEL_AID} deleted_at is set" \
  || { fail "soft-delete did not set deleted_at (body: ${DEL})"; exit 1; }

info "waiting one heartbeat interval to prove a later heartbeat does not resurrect it"
sleep 12
refresh_nodes
[ "${NODE_DELETED[$DEL_AID]:-no}" = "yes" ] && pass "${DEL_AID} stays deleted after a later heartbeat" \
  || { fail "${DEL_AID} deleted_at was cleared by a heartbeat (resurrected)"; exit 1; }

step "Case 8. All-nodes run still excludes the soft-deleted node"
T9="$(run_template_task)"
[ -n "${T9}" ] || { fail "case-9 template run returned no task_id"; exit 1; }
wait_task "${T9}" "${EXEC_TIMEOUT}"
if exec_rows "${TASK_BODY}" | cut -f2 | grep -qx "${DEL_AID}"; then
  fail "soft-deleted node ${DEL_AID} was still selected"; exit 1
else
  pass "soft-deleted node ${DEL_AID} was NOT selected"
fi
C9="$(exec_rows "${TASK_BODY}" | grep -c . || true)"
info "post-delete all-nodes run created ${C9} execution(s) (scrapy-agent-1 only)"

# ---- summary ---------------------------------------------------------------
step "Smoke summary"
printf '  passed: %d   failed: %d\n' "${PASS_COUNT}" "${FAIL_COUNT}"
if [ "${FAIL_COUNT}" -ne 0 ]; then
  printf '\n\033[31mSMOKE FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[32mSMOKE PASSED\033[0m\n'
# Teardown happens in the EXIT trap (unless KEEP_UP=1).
