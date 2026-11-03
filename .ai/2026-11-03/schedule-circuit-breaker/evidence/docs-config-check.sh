#!/usr/bin/env bash
# TC-18 assertion script (rawf evidence form (b)): exit 0 = every assertion holds.
# Run from the repository root.
set -u
fail=0
pass() { printf 'PASS %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }
has() { # has <file> <fixed-string> <label>
  if grep -qF -- "$2" "$1"; then pass "$3"; else bad "$3 ($1 lacks: $2)"; fi
}

D=docs/decisions/0025-schedule-circuit-breaker.md
if [ -f "$D" ]; then pass "0025 exists"; else bad "0025 missing"; fi
has docs/decisions/README.md "[0025](0025-schedule-circuit-breaker.md)" "decisions README indexes 0025"
has docs/decisions/0021-log-flood-guard-and-auto-disable.md "[0025](0025-schedule-circuit-breaker.md)" "0021 points to 0025"

has docs/architecture/03-execution-and-logs.md "### 任务结果记录与调度熔断" "03 has the new section heading"
# No markdown link anywhere in the repository may still target the old anchor.
if grep -rnF --include='*.md' -- "#任务结果记录与调度自动禁用)" . ; then
  bad "a markdown link still targets the old anchor"
else
  pass "no markdown link targets the old anchor"
fi
has docs/architecture/06-web-frontend.md "03-execution-and-logs.md#任务结果记录与调度熔断" "06 links the new anchor"

for key in breaker_backoff_base_seconds breaker_backoff_max_seconds breaker_escalate_after_seconds; do
  env_name="DOPILOT_SCHEDULER_$(printf '%s' "$key" | tr '[:lower:]' '[:upper:]')"
  has docs/architecture/04-configuration.md "\`[scheduler].$key\`" "04 documents $key"
  has docs/architecture/04-configuration.md "\`$env_name\`" "04 documents $env_name"
  has configs/server.example.toml "$key = " "server.example.toml sets $key"
  has configs/server.docker.toml "$key = " "server.docker.toml sets $key"
  has apps/server/dopilot_server/config/loader.py "\"$env_name\"" "loader maps $env_name"
done

for loc in zh en; do
  f=apps/web/lib/i18n/locales/$loc.ts
  for t in schedule_breaker_open schedule_breaker_held schedule_breaker_closed; do
    has "$f" "$t: {" "$loc locale has $t"
  done
  has "$f" "body_escalated:" "$loc locale has body_escalated"
done

if [ "$fail" -eq 0 ]; then echo "ALL ASSERTIONS PASSED"; else echo "SOME ASSERTIONS FAILED"; fi
exit "$fail"
