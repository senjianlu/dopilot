#!/usr/bin/env bash
# TC-04:扫描 .ai/**/evidence/ 下**其余**脚本是否有同类文本处理隐患。
# 用法(cwd 必须是仓库根):bash <本脚本>
#
# **只报告,不修改**。若扫出命中,记入实现记录交用户决定;在本任务顺手改
# 会污染 diff、超出已确认的方案范围。故本脚本恒以 0 退出(扫描本身失败除外),
# "有命中"不等于"用例失败"。
#
# 降噪(两条,均在输出中显式声明,不静默):
#   ① 跳过注释行——首个非空白字符为 # 的行只是在讨论该模式,不是在用它;
#   ② 排除两个**按设计就必须包含这些模式串**的文件:本扫描器自身(模式写在
#      grep 里)与 regression-selfcheck.sh(把 bug 作为字符串注入回退副本)。
#      排除项逐个打印,不藏。
set -uo pipefail

FIXED_A=.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh
FIXED_B=.ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh
SELF=.ai/2026-07-26/fix-evidence-script-text-bugs/evidence/scan-other-scripts.sh
INJECTOR=.ai/2026-07-26/fix-evidence-script-text-bugs/evidence/regression-selfcheck.sh
note() { printf '%s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

# 三个模式各用**字面 awk 程序**,不走 `awk -v pat=` 传动态正则。
# 原因(实测踩到):`-v` 赋值会对值做转义处理,`\\"` 被吃成 `"`,模式 3 退化
# 为 `f"[^"]*{[^}]*"`,把 bash 的 `[ -f "$f" ] || { echo "…" }` 也匹上了——
# 报出来的东西根本不是它声称要找的。字面程序没有这层歧义。
# 每个 scan_* 均先剔除注释行(首个非空白字符为 #),并保留**源文件原行号**。

# 模式 1:cut -c / cut -b
scan_cut() {
  awk '/^[[:space:]]*#/ { next }
       /cut[[:space:]]+-[cb]/ { printf "%d:%s\n", NR, $0 }' "$1"
}
# 模式 2:awk substr(
scan_substr() {
  awk '/^[[:space:]]*#/ { next }
       /substr\(/ { printf "%d:%s\n", NR, $0 }' "$1"
}
# 模式 3:同一行里既有 f-string 起始 `f"`、又有反斜杠转义引号 `\"`。
# index($0, "\\\"") 中的 "\\\"" 是 awk 字符串字面量,实际值为 2 字符 \" 。
scan_fstring() {
  awk '/^[[:space:]]*#/ { next }
       /f"/ && index($0, "\\\"") > 0 { printf "%d:%s\n", NR, $0 }' "$1"
}
# scan_any <文件>:三模式合并,供"已修文件复核"使用。
scan_any() {
  { scan_cut "$1"; scan_substr "$1"; scan_fstring "$1"; } | sort -n -u
}

note "== 扫描范围:.ai/**/evidence/ 下的 *.sh 与 *.py =="
mapfile -t all_files < <(find .ai -path '*/evidence/*' \( -name '*.sh' -o -name '*.py' \) | sort)
note "  发现 ${#all_files[@]} 个文件"

files=()
note ""
note "== 显式排除(按设计必须包含这些模式串的文件)=="
for f in "${all_files[@]}"; do
  case "$f" in
    "$SELF")     note "  排除 $f —— 本扫描器自身,模式串写在 grep/awk 参数里" ;;
    "$INJECTOR") note "  排除 $f —— 回退副本生成器,把 bug 作为字符串常量注入" ;;
    *)           files+=("$f") ;;
  esac
done
note "  实际参与扫描:${#files[@]} 个文件(已剔除注释行)"

# 逐文件输出结论(方案 TC-04 要求"逐文件列出"):每个参与扫描的文件都打一行
# OK 或 HIT,证据里可直接核对实际扫了哪些文件、各自结论如何——只打印命中项
# 的话,"无命中"与"根本没扫到"在证据上无法区分。
# 计数分两个维度并各自标明单位:命中**文件数**与命中**行数**。
hit_files=0
hit_lines=0
report() {
  local title=$1 fn=$2 nf=0 nl=0 f out c
  note ""
  note "== $title =="
  for f in "${files[@]}"; do
    out=$("$fn" "$f")
    if [ -n "$out" ]; then
      c=$(printf '%s\n' "$out" | grep -c .)
      note "  HIT  $f($c 行)"
      printf '%s\n' "$out" | sed 's|^|         |'
      nf=$((nf+1)); nl=$((nl+c))
    else
      note "  OK   $f"
    fi
  done
  note "  小计:命中 $nf 个文件 / $nl 行(共扫描 ${#files[@]} 个文件)"
  hit_files=$((hit_files+nf)); hit_lines=$((hit_lines+nl))
}

report "模式 1:cut -c / cut -b(GNU coreutils 下均按字节切,中文会被切坏)" scan_cut
report "模式 2:awk substr(本机 awk 为 mawk,同样按字节切)" scan_substr
report "模式 3:f-string 表达式内含反斜杠转义引号(SyntaxError 来源)" scan_fstring

note ""
note "== 本次已修的两个文件复核(剔注释后应无命中)=="
for f in "$FIXED_A" "$FIXED_B"; do
  out=$(scan_any "$f")
  if [ -n "$out" ]; then
    note "  ✗ $f 仍有命中:"
    printf '%s\n' "$out" | sed 's/^/      /'
  else
    note "  OK $f 三种模式均无命中"
  fi
done

note ""
note "== 扫描结论 =="
note "  参与扫描:${#files[@]} 个文件 × 3 个模式"
if [ "$hit_files" -eq 0 ]; then
  note "  命中:0 个文件 / 0 行 —— 其余 evidence 脚本未发现同类模式,无需后续处理"
else
  note "  命中:$hit_files 个文件次 / $hit_lines 行(同一文件可在多个模式下各计一次)"
  note "  按方案约定,本任务**只报告不修**,交用户决定"
fi
note "RESULT: PASS(扫描完成;命中与否不影响本用例通过)"
exit 0
