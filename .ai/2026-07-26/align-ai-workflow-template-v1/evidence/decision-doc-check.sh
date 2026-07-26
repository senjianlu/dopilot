#!/usr/bin/env bash
# TC-05:决策记录 0020 的结构、偏离清单完整性,以及索引与交叉引用一致性。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail

D20=docs/decisions/0020-ai-workflow-template-version-anchor.md
D18=docs/decisions/0018-adopt-ai-workflow-template.md
IDX=docs/decisions/README.md
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== 1. 0020 存在且为 docs/decisions/README.md 约定的四段体例 =="
if [ -f "$D20" ]; then ok "文件存在:$D20"; else bad "文件不存在:$D20"; fi
for seg in '日期' '背景' '决定' '影响'; do
  if grep -qE "^- ${seg}[::]" "$D20" 2>/dev/null; then
    ok "含「- ${seg}:」段"
  else
    bad "缺「- ${seg}:」段"
  fi
done

note ""
note "== 2. 有意偏离清单 D-1…D-5 齐全 =="
for d in D-1 D-2 D-3 D-4 D-5; do
  if grep -q "| $d |" "$D20" 2>/dev/null; then
    grep -m1 "| $d |" "$D20" | cut -c1-100 | sed 's/^/    /'
    ok "$d 已登记"
  else
    bad "偏离清单缺 $d"
  fi
done

note ""
note "== 3. 索引表含 0020 且链接目标存在 =="
row=$(grep -F '(0020-ai-workflow-template-version-anchor.md)' "$IDX" || true)
if [ -n "$row" ]; then
  note "  $row"
  ok "$IDX 索引表含 0020 行"
  target=docs/decisions/0020-ai-workflow-template-version-anchor.md
  if [ -f "$target" ]; then ok "索引链接目标存在:$target"; else bad "索引链接目标不存在:$target"; fi
else
  bad "$IDX 索引表缺 0020 行"
fi

note ""
note "== 4. 0018 含指向 0020 的交叉引用,且未被标记为已取代 =="
if grep -q '0020-ai-workflow-template-version-anchor.md' "$D18"; then
  grep -n '0020-ai-workflow-template-version-anchor.md' "$D18" | sed 's/^/    /'
  ok "0018 含指向 0020 的交叉引用"
else
  bad "0018 缺指向 0020 的交叉引用"
fi
if grep -qE '已被[[:space:]]*[0-9]{4}[[:space:]]*取代' "$D18"; then
  bad "0018 被加上了「已被 NNNN 取代」标记;0020 是补充版本维度,并未推翻 0018"
else
  ok "0018 未被标记为已取代(符合 docs/decisions/README.md:该标记只用于推翻)"
fi

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
