#!/usr/bin/env bash
# TC-14: all three compose files validate AND EVERY service is asserted one by
# one (via `docker compose config --format json`) to carry the bounded json-file
# log driver (max-size=10m, max-file=3); redis additionally has
# maxmemory/noeviction/auto-aof-rewrite. Any service missing a bound fails.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)/deploy/docker"
export DOPILOT_AGENT_TOKEN=dummy-token-1234567890 DOPILOT_SERVER_URL=http://x:5000 REDIS_PASSWORD=x
fail=0

for f in docker-compose.yml docker-compose.server.yml docker-compose.agent.yml; do
  echo "=== $f ==="
  json=$(docker compose -f "$f" config --format json 2>&1) || {
    echo "CONFIG FAILED"; echo "$json"; fail=1; continue; }
  echo "config: OK"
  # Per-service assertion: the file fails unless EVERY service has
  # logging.options {max-size:10m, max-file:3}. One line printed per service.
  COMPOSE_JSON="$json" python3 - <<'PY' || fail=1
import json, os
data = json.loads(os.environ["COMPOSE_JSON"])
svcs = data.get("services", {})
assert svcs, "no services rendered"
ok = True
for name, s in svcs.items():
    opts = (s.get("logging") or {}).get("options") or {}
    good = opts.get("max-size") == "10m" and opts.get("max-file") == "3"
    print(f"  service {name}: logging.options={opts} -> {'OK' if good else 'MISSING/BAD'}")
    ok = ok and good
print(f"  all {len(svcs)} services bounded: {ok}")
raise SystemExit(0 if ok else 1)
PY
done

echo "=== redis maxmemory/noeviction/auto-aof-rewrite (all-in-one rendered command) ==="
json=$(docker compose -f docker-compose.yml config --format json 2>/dev/null)
COMPOSE_JSON="$json" python3 - <<'PY' || fail=1
import json, os
data = json.loads(os.environ["COMPOSE_JSON"])
cmd = data["services"]["redis"].get("command") or []
cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
checks = {
    "maxmemory": "--maxmemory" in cmd,
    "noeviction": "noeviction" in cmd,
    "auto-aof-rewrite": "auto-aof-rewrite-percentage" in cmd,
}
for k, v in checks.items():
    print(f"  redis {k}: {'OK' if v else 'MISSING'}")
raise SystemExit(0 if all(checks.values()) else 1)
PY

echo "FAIL=$fail"
exit $fail
