#!/usr/bin/env bash
# TC-02:.ai-workflow/TEMPLATE-VERSION 的格式与取值断言(6 项)+ 反向自检。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail

F=.ai-workflow/TEMPLATE-VERSION
SRC_URL="https://github.com/senjianlu/ai-workflow-template"
ADOPTED_EXPECT="adopted: 2026-07-26"
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

# check_file <路径>:6 项断言,任一不过返回 1。反向自检复用同一函数。
check_file() {
  local f=$1 local_fail=0
  [ -f "$f" ] || { echo "  [1] 文件不存在:$f"; return 1; }
  echo "  [1] 文件存在:$f"

  local n; n=$(wc -l < "$f")
  if [ "$n" -eq 3 ]; then echo "  [2] 行数=3"; else echo "  [2] 行数=$n,期望 3"; local_fail=1; fi

  local keys; keys=$(cut -d: -f1 < "$f" | paste -sd,)
  if [ "$keys" = "version,source,adopted" ]; then
    echo "  [3] 字段名与顺序=version,source,adopted"
  else
    echo "  [3] 字段名与顺序=$keys,期望 version,source,adopted"; local_fail=1
  fi

  local v; v=$(sed -n '1s/^version:[[:space:]]*//p' "$f")
  if [ "$v" = "1.0.0" ]; then echo "  [4] version=1.0.0"; else echo "  [4] version=[$v],期望 1.0.0"; local_fail=1; fi

  local s; s=$(sed -n '2s/^source:[[:space:]]*//p' "$f")
  if [ "$s" = "$SRC_URL" ]; then echo "  [5] source=$s"; else echo "  [5] source=[$s],期望 $SRC_URL"; local_fail=1; fi

  local a; a=$(sed -n '3p' "$f")
  if [ "$a" = "$ADOPTED_EXPECT" ]; then
    echo "  [6a] adopted 整行严格匹配:[$a]"
  else
    echo "  [6a] adopted 整行=[$a],期望 [$ADOPTED_EXPECT]"; local_fail=1
  fi
  if grep -q '拷入 consumer' "$f"; then
    echo "  [6b] 仍含模板占位文案「拷入 consumer」"; local_fail=1
  else
    echo "  [6b] 不含模板占位文案「拷入 consumer」"
  fi

  return "$local_fail"
}

note "== 正向:核验仓库内的 $F =="
if check_file "$F"; then ok "6 项断言全部通过"; else bad "存在未通过的断言"; fi

note ""
note "== 反向自检:adopted 换成另一合法日期(2026-07-24)必须被拒 =="
SCRATCH=${SCRATCH_DIR:-/tmp/claude-1000/-home-rabbir-Projects-dopilot/c710bc7e-e506-4ef8-a504-c70181b8a2f7/scratchpad}
mkdir -p "$SCRATCH/tc02"
sed 's/^adopted: .*/adopted: 2026-07-24/' "$F" > "$SCRATCH/tc02/TEMPLATE-VERSION.bad-date"
note "  副本内容:"; sed 's/^/    /' "$SCRATCH/tc02/TEMPLATE-VERSION.bad-date"
if check_file "$SCRATCH/tc02/TEMPLATE-VERSION.bad-date"; then
  bad "反向自检失效:错误的 adopted 日期竟然通过了检测(说明只校验了格式)"
else
  ok "反向自检有效:错误的 adopted 日期被拒"
fi

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
