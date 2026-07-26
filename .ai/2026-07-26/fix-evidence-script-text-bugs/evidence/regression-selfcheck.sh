#!/usr/bin/env bash
# TC-03(异常/反向路径):证明 TC-01 与 TC-02 的检测不是恒真通过。
# 用法(cwd 必须是仓库根):bash <本脚本>
#
# 做法:脚本自己在 scratchpad 造两份**打回原样**(带 bug)的副本,
#   回退 A = decision-doc-check.sh 恢复 `| cut -c1-100`
#   回退 B = reverse-selfcheck.sh 恢复 f-string 内的反斜杠写法
# 分别运行,断言两个缺陷**必然重现**。副本由本脚本内的 sed 就地生成,
# 生成命令与执行体一一对应,单条命令即可完整复现。
set -uo pipefail

SCRATCH=${SCRATCH_DIR:-/tmp/claude-1000/-home-rabbir-Projects-dopilot/c710bc7e-e506-4ef8-a504-c70181b8a2f7/scratchpad}/tc03-regress
A_SRC=.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh
B_SRC=.ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
mkdir -p "$SCRATCH"

note "== 回退 A:decision-doc-check.sh 恢复 cut -c1-100 =="
# 生成命令:sed 's#| sed .s/\^/    /.#| cut -c1-100 &#' —— 直接在 grep 后插回 cut
sed 's#grep -m1 "| \$d |" "\$D20" | sed#grep -m1 "| $d |" "$D20" | cut -c1-100 | sed#' \
  "$A_SRC" > "$SCRATCH/decision-doc-check.reverted.sh"
if diff -q "$A_SRC" "$SCRATCH/decision-doc-check.reverted.sh" >/dev/null; then
  bad "回退 A 未生效(副本与现版本相同),本自检无意义"
else
  note "  已生成带 bug 的副本,差异行:"
  diff "$A_SRC" "$SCRATCH/decision-doc-check.reverted.sh" | sed 's/^/    /'
fi

note ""
note "  运行回退 A 副本并做 UTF-8 校验(期望:校验失败)"
bash "$SCRATCH/decision-doc-check.reverted.sh" > "$SCRATCH/a.out" 2>&1
note "  副本退出码=$?"
if iconv -f UTF-8 -t UTF-8 < "$SCRATCH/a.out" >/dev/null 2>&1; then
  bad "回退 A 的输出竟然是合法 UTF-8 —— TC-01 的 iconv 检测形同虚设"
else
  ok "回退 A 重现了坏字节(iconv 校验失败),TC-01 的检测确实在测这个 bug"
  note "  出问题的行(cat -A,截取尾部):"
  grep -m1 'D-1' "$SCRATCH/a.out" | cat -A | tail -c 140 | sed 's/^/    /'
  note ""
fi

note ""
note "== 回退 B:reverse-selfcheck.sh 恢复 f-string 内反斜杠 =="
# 生成命令:把两行(label 赋值 + 使用)换回单行的反斜杠写法
python3 - "$B_SRC" "$SCRATCH/reverse-selfcheck.reverted.sh" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
fixed = ('        label = s.get("name") or s.get("uses")\n'
         '        print(f"      [{i}] {label}")\n')
buggy = '        print(f"      [{i}] {s.get(\\"name\\", s.get(\\"uses\\"))}")\n'
if fixed not in text:
    print("  回退 B 失败:在现版本中找不到修复后的两行")
    sys.exit(3)
open(dst, "w", encoding="utf-8").write(text.replace(fixed, buggy))
print("  已生成带 bug 的副本(两行合并回反斜杠单行写法)")
PY
gen_rc=$?
[ "$gen_rc" -eq 0 ] || bad "回退 B 副本生成失败(rc=$gen_rc)"

if [ -f "$SCRATCH/reverse-selfcheck.reverted.sh" ]; then
  note "  差异行:"
  diff "$B_SRC" "$SCRATCH/reverse-selfcheck.reverted.sh" | sed 's/^/    /'
  note ""
  note "  运行回退 B 副本(期望:出现 SyntaxError)"
  bash "$SCRATCH/reverse-selfcheck.reverted.sh" > "$SCRATCH/b.out" 2>&1
  note "  副本退出码=$?"
  if grep -q 'SyntaxError' "$SCRATCH/b.out"; then
    ok "回退 B 重现了 SyntaxError,TC-02 的检测确实在测这个 bug"
    grep -n -B2 'SyntaxError' "$SCRATCH/b.out" | head -6 | sed 's/^/    /'
  else
    bad "回退 B 未出现 SyntaxError —— TC-02 的检测形同虚设"
  fi
fi

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS —— 两个缺陷在回退副本上均可重现,检测非恒真通过" || note "RESULT: FAIL"
exit "$fail"
