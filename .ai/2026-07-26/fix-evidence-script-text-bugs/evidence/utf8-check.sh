#!/usr/bin/env bash
# TC-01:decision-doc-check.sh 修复后,输出必须是合法 UTF-8,且 D-1…D-5
# 五行被**完整**打印(未被任何形式截断)。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail

TARGET=.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh
D20=docs/decisions/0020-ai-workflow-template-version-anchor.md
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
[ -f "$TARGET" ] || { echo "找不到 $TARGET" >&2; exit 2; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

note "== 1. 重跑 decision-doc-check.sh(功能须未被改坏)=="
bash "$TARGET" > "$tmp/out.txt" 2>&1
rc=$?
note "  退出码=$rc"
sed 's/^/  | /' "$tmp/out.txt"
if [ "$rc" -eq 0 ]; then
  ok "脚本自身仍 exit=0,断言逻辑未被改坏"
else
  bad "脚本退出码为 $rc,修改可能破坏了原有断言"
fi

note ""
note "== 2. 全部输出的 UTF-8 合法性校验 =="
if iconv -f UTF-8 -t UTF-8 < "$tmp/out.txt" > /dev/null 2>"$tmp/iconv.err"; then
  ok "iconv -f UTF-8 -t UTF-8 校验通过,输出无非法字节"
else
  bad "输出含非法 UTF-8 字节:"
  sed 's/^/    /' "$tmp/iconv.err"
  note "  含坏字节的行(cat -A 展示):"
  grep -naxv '.*' "$tmp/out.txt" | sed 's/^/    /' || true
fi

note ""
note "== 3. D-1…D-5 五行完整性(与 0020 源文件逐行比对)=="
for d in D-1 D-2 D-3 D-4 D-5; do
  src=$(grep -m1 "| $d |" "$D20" | sed 's/^[[:space:]]*//')
  got=$(grep -m1 "| $d |" "$tmp/out.txt" | sed 's/^[[:space:]]*//')
  src_chars=$(printf '%s' "$src" | wc -m)
  got_chars=$(printf '%s' "$got" | wc -m)
  if [ -z "$got" ]; then
    bad "$d 未在输出中出现"
    continue
  fi
  if [ "$src" = "$got" ]; then
    ok "$d 完整打印(${got_chars} 字符,与源文件逐字符一致)"
  else
    bad "$d 输出与源文件不一致(源 ${src_chars} 字符 / 实得 ${got_chars} 字符)—— 疑似仍被截断"
    note "    源:$src"
    note "    得:$got"
  fi
done

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS —— 输出合法 UTF-8 且五行完整" || note "RESULT: FAIL"
exit "$fail"
