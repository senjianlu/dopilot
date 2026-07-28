#!/usr/bin/env bash
# TC-06:K8s StatefulSet 的 agent env 键名与 fieldRef 关联断言。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail
export LC_ALL=C

F=deploy/kubernetes/agent/statefulset.yaml
fail=0
note() { printf '%s\n' "$*"; }
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f "$F" ] || { echo "找不到 $F" >&2; exit 2; }

note "== 1. env 键名原文(含上下文) =="
grep -nE -A3 'name: (DOPILOT_)?AGENT_(ID|WORKDIR)' "$F" | sed 's/^/    /'

note ""
note "== 2. 断言 =="
grep -qE '^[[:space:]]*- name: DOPILOT_AGENT_ID$' "$F" \
  && ok "存在 DOPILOT_AGENT_ID" || bad "缺 DOPILOT_AGENT_ID"
grep -qE '^[[:space:]]*- name: DOPILOT_AGENT_WORKDIR$' "$F" \
  && ok "存在 DOPILOT_AGENT_WORKDIR" || bad "缺 DOPILOT_AGENT_WORKDIR"
grep -A3 'name: DOPILOT_AGENT_ID' "$F" | grep -q 'fieldPath: metadata.name' \
  && ok "DOPILOT_AGENT_ID 仍由 fieldRef metadata.name 取值(每 Pod 唯一 id 未丢)" \
  || bad "DOPILOT_AGENT_ID 的 fieldRef metadata.name 关联丢失"
grep -A2 'name: DOPILOT_AGENT_WORKDIR' "$F" | grep -qE 'value: */agent-data' \
  && ok "DOPILOT_AGENT_WORKDIR 值仍为 /agent-data" || bad "DOPILOT_AGENT_WORKDIR 值不对"
if grep -qE '^[[:space:]]*- name: (AGENT_ID|AGENT_WORKDIR)$' "$F"; then
  bad "仍存在裸旧键 name: AGENT_ID / AGENT_WORKDIR"
else
  ok "无裸旧键"
fi

note ""
note "== 3. 反向自检:把新键改回旧名的副本必须被上面的断言判失败 =="
tmp=$(mktemp)
sed 's/- name: DOPILOT_AGENT_ID$/- name: AGENT_ID/' "$F" > "$tmp"
if grep -qE '^[[:space:]]*- name: (AGENT_ID|AGENT_WORKDIR)$' "$tmp"; then
  ok "裸旧键检测在回退副本上确实命中(断言有效,非恒真)"
else
  bad "裸旧键检测对回退副本无反应,该断言恒真、无判别力"
fi
rm -f "$tmp"

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
