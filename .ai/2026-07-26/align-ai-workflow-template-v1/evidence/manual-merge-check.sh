#!/usr/bin/env bash
# TC-08:需人工合并类的逐 hunk 处置核验。
#
# 用法(cwd 必须是仓库根):bash <本脚本> <模板独立克隆的绝对路径>
# 退出码:0=每个 v1.0.0 增量 hunk 都被显式处置且处置可核实;非 0=有漏处置 /
#         台账造假 / 锚点不存在 / CLAUDE.md 偏离超出 D-2 / AGENTS.md 丢章节。
#
# 设计要点(应 plan 评审第 1 轮 R-02):hunk 集合**从模板现算**,再与台账做
# 集合相等断言——若只遍历台账,漏登记的 hunk 永远不会被发现,脚本会恒真通过。
#
# 反向自检(应实现层评审第 02 轮 R-01):第 8 节把"台账缺行/多行必须被检出"
# 的验证**内置在本脚本内**,伪造台账由脚本自己生成到 scratchpad。此前该验证
# 靠脚本外部搭建(sed 改写 LEDGER 变量后另存副本),证据里只能写成占位命令、
# 无法复现;现在一条 `bash <本脚本> "$TPL"` 即可跑出正反两向的完整输出。
set -uo pipefail

TPL=${1:-}
TD=.ai/2026-07-26/align-ai-workflow-template-v1
LEDGER="$TD/evidence/manual-merge-ledger.tsv"
DECISION=docs/decisions/0020-ai-workflow-template-version-anchor.md
SCRATCH=${SCRATCH_DIR:-/tmp/claude-1000/-home-rabbir-Projects-dopilot/c710bc7e-e506-4ef8-a504-c70181b8a2f7/scratchpad}/tc08
PATHS=(AGENTS.md CLAUDE.md README.md .agents/skills skills-lock.json)
fail=0
note() { printf '%s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }
softbad() { printf 'FAIL  %s\n' "$*"; }   # 只报告不置位,供第 8 节反向自检复用

[ -n "$TPL" ] || { echo "用法:bash $0 <模板克隆路径>" >&2; exit 2; }
[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
[ -f "$LEDGER" ] || { echo "台账不存在:$LEDGER" >&2; exit 2; }

note "== 1. 从模板现算 48a435a..v1.0.0 在人工合并类路径上的 hunk 集合 =="
computed=$(for p in "${PATHS[@]}"; do
  git -C "$TPL" diff --unified=0 48a435a v1.0.0 -- "$p" \
    | grep '^@@' | sed 's/\(@@[^@]*@@\).*/\1/' | sed "s|^|$p\t|"
done | sort)
printf '%s\n' "$computed" | sed 's/^/  /'
note "现算 hunk 数:$(printf '%s\n' "$computed" | grep -c .)"

# check_ledger_set <台账文件> [silent]
#   与 $computed 做集合相等断言。silent 非空时只报告、不置位全局 fail。
#   返回 0=集合相等;1=有缺行(漏处置)或多行(台账造假)。
check_ledger_set() {
  local ledger=$1 silent=${2:-} report=bad rc=0 declared oc od
  [ -n "$silent" ] && report=softbad
  declared=$(grep -v '^#' "$ledger" | grep -v '^[[:space:]]*$' | cut -f1,2 | sort)
  note "  台账文件:$ledger(数据行 $(printf '%s\n' "$declared" | grep -c .) 条)"
  oc=$(comm -23 <(printf '%s\n' "$computed") <(printf '%s\n' "$declared"))
  od=$(comm -13 <(printf '%s\n' "$computed") <(printf '%s\n' "$declared"))
  if [ -n "$oc" ]; then
    printf '%s\n' "$oc" | sed 's/^/  MISSING-IN-LEDGER  /'
    "$report" "存在未被处置的 v1.0.0 增量 hunk(漏对齐)"
    rc=1
  fi
  if [ -n "$od" ]; then
    printf '%s\n' "$od" | sed 's/^/  NOT-IN-TEMPLATE    /'
    "$report" "台账声明了模板中不存在的 hunk(台账造假)"
    rc=1
  fi
  [ "$rc" -eq 0 ] && note "  OK  集合相等"
  return "$rc"
}

note ""
note "== 2. 台账声明的 hunk 集合 =="
grep -v '^#' "$LEDGER" | grep -v '^[[:space:]]*$' | cut -f1,2 | sort | sed 's/^/  /'

note ""
note "== 3. 集合相等断言(正式台账)=="
check_ledger_set "$LEDGER"

note ""
note "== 4. 逐条 disposition 校验 =="
while IFS=$'\t' read -r p hunk disp _note; do
  case "$p" in ''|'#'*) continue ;; esac
  case "$disp" in
    divergence:D-*)
      dn=${disp#divergence:}
      if grep -q "| $dn |" "$DECISION"; then
        note "  OK  $p $hunk -> $disp(在 0020 偏离清单中找到 $dn)"
      else
        bad "$p $hunk 声称 $disp,但 $DECISION 中无 $dn 条目"
      fi
      ;;
    absorbed:*)
      anchor=${disp#absorbed:}
      if [ -e "$anchor" ]; then
        note "  OK  $p $hunk -> absorbed,锚点存在:$anchor"
      else
        bad "$p $hunk 声称 absorbed 到 $anchor,但该路径不存在"
      fi
      ;;
    n/a-template-doc|no-op)
      note "  OK  $p $hunk -> $disp"
      ;;
    *)
      bad "$p $hunk 的 disposition 不在四词表内:[$disp]"
      ;;
  esac
done < <(grep -v '^#' "$LEDGER" | grep -v '^[[:space:]]*$')

note ""
note "== 5. CLAUDE.md 全文比对(与模板同源,偏离须恰为 D-2)=="
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git -C "$TPL" show v1.0.0:CLAUDE.md > "$tmp/CLAUDE.tpl"
added=$(diff "$tmp/CLAUDE.tpl" CLAUDE.md | grep -c '^> ' || true)
removed=$(diff "$tmp/CLAUDE.tpl" CLAUDE.md | grep '^< ' || true)
removed_n=$(printf '%s\n' "$removed" | grep -c . || true)
note "  新增行=$added 删除行=$removed_n"
printf '%s\n' "$removed" | sed 's/^/    /'
[ "$added" -eq 0 ] || bad "CLAUDE.md 相对 v1.0.0 有新增行($added),D-2 只允许一行删除"
[ "$removed_n" -eq 1 ] || bad "CLAUDE.md 删除行数为 $removed_n,期望恰好 1(D-2)"
if printf '%s\n' "$removed" | grep -q 'docs/decisions/0003'; then
  note "  OK  被删行指向模板仓库的 docs/decisions/0003,符合 D-2"
else
  bad "CLAUDE.md 被删行不含 docs/decisions/0003,与 D-2 不符"
fi

note ""
note "== 6. AGENTS.md 章节骨架断言(模板 v1.0.0 的 ## 顶级章节须全在)=="
while read -r h; do
  [ -n "$h" ] || continue
  if grep -Fq "$h" AGENTS.md; then
    note "  OK  $h"
  else
    bad "AGENTS.md 缺失模板 v1.0.0 的顶级章节:$h"
  fi
done < <(git -C "$TPL" show v1.0.0:AGENTS.md | grep '^## ')

note ""
note "== 7. .agents/skills 与 skills-lock.json:模板 v1.0.0 侧无可并项 =="
tracked=$(git -C "$TPL" ls-tree -r --name-only v1.0.0 -- .agents skills-lock.json)
if [ -z "$tracked" ]; then
  note "OK    git ls-tree -r v1.0.0 -- .agents skills-lock.json 输出为空(no-op 属实)"
else
  printf '%s\n' "$tracked" | sed 's/^/  /'
  bad "模板 v1.0.0 侧存在 .agents/skills 或 skills-lock.json,需人工合并而非 no-op"
fi

note ""
note "== 8. 反向自检:集合相等断言必须能识破台账缺行与多行 =="
note "  伪造台账由本脚本生成到 $SCRATCH,生成命令即下方注释所示,无需外部搭建。"
mkdir -p "$SCRATCH"

# 伪造 A:删掉一条真实 hunk 行 -> 应报 MISSING-IN-LEDGER
#   生成命令:grep -v $'^README.md\t@@ -79,0 +91,37 @@' "$LEDGER" > "$SCRATCH/ledger-missing-row.tsv"
grep -v $'^README.md\t@@ -79,0 +91,37 @@' "$LEDGER" > "$SCRATCH/ledger-missing-row.tsv"
note ""
note "  --- 伪造 A:台账缺 1 行(README.md @@ -79,0 +91,37 @@)---"
if check_ledger_set "$SCRATCH/ledger-missing-row.tsv" silent; then
  bad "反向自检失效:缺行台账竟然通过集合相等断言"
else
  note "  OK  伪造 A 被拒(缺行可被检出)"
fi

# 伪造 B:追加一条模板中不存在的 hunk 行 -> 应报 NOT-IN-TEMPLATE
#   生成命令:{ cat "$LEDGER"; printf 'README.md\t@@ -999 +999 @@\tno-op\t伪造行\n'; } > "$SCRATCH/ledger-bogus-row.tsv"
{ cat "$LEDGER"; printf 'README.md\t@@ -999 +999 @@\tno-op\t伪造行\n'; } > "$SCRATCH/ledger-bogus-row.tsv"
note ""
note "  --- 伪造 B:台账多 1 行(模板中不存在的 @@ -999 +999 @@)---"
if check_ledger_set "$SCRATCH/ledger-bogus-row.tsv" silent; then
  bad "反向自检失效:含伪造行的台账竟然通过集合相等断言"
else
  note "  OK  伪造 B 被拒(多行可被检出)"
fi

note ""
if [ "$fail" -eq 0 ]; then
  note "RESULT: PASS —— 人工合并类的每个 v1.0.0 增量 hunk 均已显式处置且处置可核实;"
  note "        集合相等断言经正反两向自检,非恒真通过"
else
  note "RESULT: FAIL"
fi
exit "$fail"
