#!/usr/bin/env bash
# TC-05:agent 接入栈缺 DOPILOT_REDIS_PASSWORD 且缺 DOPILOT_REDIS_URL 时,
# compose 的 `:?` 必须快速失败并点名新变量名(改名后未丢失该语义)。
# 附对照:补上 DOPILOT_REDIS_URL 即可解除 => `:?` 仅在两者皆缺时触发。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail
export LC_ALL=C

D=deploy/docker
fail=0
note() { printf '%s\n' "$*"; }
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== 1. 两者皆缺(期望非 0 退出 + 点名 DOPILOT_REDIS_PASSWORD) =="
out=$(env -u DOPILOT_REDIS_PASSWORD -u DOPILOT_REDIS_URL -C "$D" \
        DOPILOT_AGENT_TOKEN=tc05-agent-token-1234567890 \
        DOPILOT_SERVER_URL=http://tc05-server:5000 \
        docker compose -f docker-compose.agent.yml config 2>&1)
rc=$?
printf '%s\n' "$out" | sed 's/^/    /'
note "  退出码=$rc"
[ "$rc" -ne 0 ] && ok "缺 DOPILOT_REDIS_PASSWORD 时快速失败" || bad "未快速失败(退出码 0)"
printf '%s\n' "$out" | grep -q 'DOPILOT_REDIS_PASSWORD' \
  && ok "错误信息点名 DOPILOT_REDIS_PASSWORD" || bad "错误信息未点名 DOPILOT_REDIS_PASSWORD"
printf '%s\n' "$out" | grep -qE '\bREDIS_PASSWORD\b' \
  && bad "错误信息里出现裸旧名 REDIS_PASSWORD(说明 :? 提示词未同步改名)" \
  || ok "错误信息不含裸旧名"

note ""
note "== 2. 对照:补 DOPILOT_REDIS_URL 后应解析成功 =="
out2=$(env -u DOPILOT_REDIS_PASSWORD -C "$D" \
         DOPILOT_REDIS_URL=redis://:pw@h:6379/0 \
         DOPILOT_AGENT_TOKEN=tc05-agent-token-1234567890 \
         DOPILOT_SERVER_URL=http://tc05-server:5000 \
         docker compose -f docker-compose.agent.yml config 2>&1)
rc2=$?
printf '%s\n' "$out2" | grep -E 'DOPILOT_REDIS_URL' | sed 's/^/    /'
note "  退出码=$rc2"
[ "$rc2" -eq 0 ] && ok "补 DOPILOT_REDIS_URL 即解除 => :? 仅在两者皆缺时触发" \
  || bad "补 DOPILOT_REDIS_URL 后仍失败"

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
