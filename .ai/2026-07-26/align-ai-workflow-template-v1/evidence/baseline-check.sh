#!/usr/bin/env bash
# TC-01:可整体替换类的全量基线对齐核验(dopilot vs ai-workflow-template v1.0.0)
#
# 用法(cwd 必须是仓库根):bash <本脚本> <模板独立克隆的绝对路径>
# 退出码:0=全部符合期望;非 0=存在漏对齐 / 未登记差异 / 意外多出文件。
#
# 设计要点(应 plan 评审第 2 轮 R-01):受管路径集**不手写**,从模板 v1.0.0
# 现算,并做双向比对——只比"模板有的"会漏掉 consumer 私自塞进受管目录的文件。
set -uo pipefail

TPL=${1:-}
PINNED_SHA=2aeab2eaca28b1364a46ec7cfc9195849cc61b68
fail=0
note() { printf '%s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }
softbad() { printf 'FAIL  %s\n' "$*"; }   # 只报告不置位,供反向自检复用检测函数

[ -n "$TPL" ] || { echo "用法:bash $0 <模板克隆路径>" >&2; exit 2; }
[ -d "$TPL/.git" ] || { echo "不是 git 克隆:$TPL" >&2; exit 2; }
[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== 0. 基准锚定 =="
actual_sha=$(git -C "$TPL" rev-parse v1.0.0^{commit} 2>/dev/null)
note "模板克隆路径 : $TPL"
note "v1.0.0 解析为: ${actual_sha:-<无此 tag>}"
note "期望(钉死)  : $PINNED_SHA"
if [ "$actual_sha" = "$PINNED_SHA" ]; then
  note "OK    v1.0.0 tag 未漂移"
else
  bad "v1.0.0 解析结果与钉死 SHA 不符,比对基准失真,后续结论一律不可信"
  exit 1
fi

# 受管路径 glob(取自模板 CHANGELOG.md 头部「可整体替换」归类行)
is_managed() {
  case "$1" in
    .ai-workflow/*|.claude/hooks/*|.claude/skills/rawf-*|.claude/settings.json|.githooks/*|.gitmessage) return 0 ;;
    *) return 1 ;;
  esac
}

note ""
note "== 1. 从模板 v1.0.0 现算受管路径全集 =="
tpl_paths=$(git -C "$TPL" ls-tree -r --name-only v1.0.0 | while read -r p; do is_managed "$p" && echo "$p"; done | sort)
note "$tpl_paths" | sed 's/^/  /'
note "模板侧受管路径数:$(printf '%s\n' "$tpl_paths" | grep -c .)"

note ""
note "== 2. 从 dopilot 侧现算同一组 glob 的路径全集(双向比对用)=="
loc_paths=$( { git ls-files; git ls-files --others --exclude-standard; } | while read -r p; do is_managed "$p" && echo "$p"; done | sort -u)
note "$loc_paths" | sed 's/^/  /'
note "dopilot 侧受管路径数:$(printf '%s\n' "$loc_paths" | grep -c .)"

# check_review_standards <模板侧 blob> <dopilot 侧文件>
#   D-1 的严格断言:相对模板 v1.0.0 **只有删除、无新增**,且被删块与模板
#   在 48a435a..v1.0.0 之间**新增的那 4 行逐字节相等**。
#   预期块不写死在本脚本里,而是从模板 diff 现算——写死等于把"期望"和
#   "事实"都攥在实现者手里,现算才能证明删掉的确实就是模板加的那一块。
#   返回 0=符合 D-1;非 0=不符。
#   CRS_SILENT 非空时只打印 FAIL 行、不污染全局 fail(供反向自检调用)。
check_review_standards() {
  local tpl_blob=$1 loc=$2 d="$tmp/crs.$$"
  local report=bad
  [ -n "${CRS_SILENT:-}" ] && report=softbad
  mkdir -p "$d"
  git -C "$TPL" diff 48a435a v1.0.0 -- .ai-workflow/review-standards.md \
    | grep '^+' | grep -v '^+++' | sed 's/^+//' > "$d/expected"
  diff "$tpl_blob" "$loc" | grep '^> ' | sed 's/^> //' > "$d/added"
  diff "$tpl_blob" "$loc" | grep '^< ' | sed 's/^< //' > "$d/removed"

  local rc=0
  local n_add n_rem n_exp
  n_add=$(grep -c . < "$d/added" || true)
  n_rem=$(grep -c . < "$d/removed" || true)
  n_exp=$(grep -c . < "$d/expected" || true)
  note "        新增行=$n_add 删除行=$n_rem 模板新增块行数=$n_exp"
  note "        —— 模板 48a435a..v1.0.0 新增的块(预期被删块,现算):"
  sed 's/^/           | /' "$d/expected"
  note "        —— dopilot 侧实际被删块:"
  sed 's/^/           | /' "$d/removed"

  if [ "$n_add" -ne 0 ]; then
    "$report" "review-standards.md 相对模板有新增行($n_add 行),D-1 只允许删除"
    rc=1
  fi
  if cmp -s "$d/expected" "$d/removed"; then
    note "        OK 被删块与模板新增块**逐字节相等**($n_rem 行)"
  else
    "$report" "review-standards.md 被删块与模板 v1.0.0 新增块不一致(逐字节比对失败)"
    diff -u "$d/expected" "$d/removed" | sed 's/^/           /'
    rc=1
  fi
  rm -rf "$d"
  return "$rc"
}

# 例外表:仅此 3 条允许非 IDENTICAL,其余一律必须 IDENTICAL
expect_of() {
  case "$1" in
    .ai-workflow/TEMPLATE-VERSION) echo EXPECTED-DIFF ;;
    .ai-workflow/review-standards.md) echo EXPECTED-DIFF ;;
    .claude/skills/rawf-stack-scrapy/SKILL.md) echo EXPECTED-ABSENT ;;
    *) echo IDENTICAL ;;
  esac
}

note ""
note "== 3. 逐路径比对(SHA-256)=="
n_identical=0; n_expdiff=0; n_expabsent=0; n_unexpected=0
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

while read -r p; do
  [ -n "$p" ] || continue
  want=$(expect_of "$p")
  git -C "$TPL" show "v1.0.0:$p" > "$tmp/tpl.blob" 2>/dev/null || : > "$tmp/tpl.blob"
  tsha=$(sha256sum < "$tmp/tpl.blob" | cut -d' ' -f1)
  if [ -e "$p" ]; then
    lsha=$(sha256sum < "$p" | cut -d' ' -f1)
  else
    lsha="<ABSENT>"
  fi
  printf '  %s\n' "$p"
  printf '        tpl-sha256=%s\n' "$tsha"
  printf '        loc-sha256=%s\n' "$lsha"

  if [ "$lsha" = "<ABSENT>" ]; then
    if [ "$want" = EXPECTED-ABSENT ]; then
      note "        -> EXPECTED-ABSENT(D-4:Scrapy 栈 skill 有意不引入)"
      n_expabsent=$((n_expabsent+1))
    else
      bad "$p 在 dopilot 侧缺失,但未登记为例外 -> UNEXPECTED-MISSING"
      n_unexpected=$((n_unexpected+1))
    fi
    continue
  fi

  if [ "$tsha" = "$lsha" ]; then
    if [ "$want" = IDENTICAL ]; then
      note "        -> IDENTICAL"
      n_identical=$((n_identical+1))
    else
      bad "$p 登记为 $want 却与模板全等,例外表与事实不符"
      n_unexpected=$((n_unexpected+1))
    fi
    continue
  fi

  # 有差异:必须是登记过的 EXPECTED-DIFF,且差异内容符合细则
  if [ "$want" != EXPECTED-DIFF ]; then
    bad "$p 与模板 v1.0.0 不一致且未登记为例外 -> UNEXPECTED-DIFF"
    diff -u "$tmp/tpl.blob" "$p" | sed 's/^/          /'
    n_unexpected=$((n_unexpected+1))
    continue
  fi

  case "$p" in
    .ai-workflow/TEMPLATE-VERSION)
      # 细则:除 adopted 行外与模板全等;adopted 整行严格等于目标值
      grep -v '^adopted:' "$tmp/tpl.blob" > "$tmp/a"; grep -v '^adopted:' "$p" > "$tmp/b"
      if diff -q "$tmp/a" "$tmp/b" >/dev/null; then
        note "        -> EXPECTED-DIFF:除 adopted 行外与 v1.0.0 全等 OK"
      else
        bad "$p 的非 adopted 行也与模板不一致"; diff -u "$tmp/a" "$tmp/b" | sed 's/^/          /'
      fi
      adopted_line=$(grep '^adopted:' "$p")
      if [ "$adopted_line" = "adopted: 2026-07-26" ]; then
        note "        -> adopted 整行严格匹配:[$adopted_line]"
      else
        bad "$p 的 adopted 行不等于 'adopted: 2026-07-26',实际:[$adopted_line]"
      fi
      n_expdiff=$((n_expdiff+1))
      ;;
    .ai-workflow/review-standards.md)
      note "        -> EXPECTED-DIFF(D-1):被删块须与模板新增块逐字节相等"
      check_review_standards "$tmp/tpl.blob" "$p"
      n_expdiff=$((n_expdiff+1))
      ;;
  esac
done <<< "$tpl_paths"

note ""
note "== 4. 反向:dopilot 侧多出的受管路径(模板 v1.0.0 无)=="
extra=$(comm -13 <(printf '%s\n' "$tpl_paths") <(printf '%s\n' "$loc_paths"))
n_extra=$(printf '%s\n' "$extra" | grep -c . || true)
if [ "$n_extra" -eq 0 ]; then
  note "OK    无 UNEXPECTED-EXTRA"
else
  printf '%s\n' "$extra" | sed 's/^/  /'
  bad "dopilot 侧存在模板 v1.0.0 没有的受管路径 -> UNEXPECTED-EXTRA"
  n_unexpected=$((n_unexpected+1))
fi

note ""
note "== 5. 反向自检:D-1 断言必须能识破"删了 4 行但不是那 4 行" =="
# 构造两份伪造的 dopilot 侧 review-standards.md,均满足旧逻辑的
# "删除 4 行 + 至少一行含 Scrapy",但都不该通过逐字节断言。
git -C "$TPL" show v1.0.0:.ai-workflow/review-standards.md > "$tmp/rs.v100"
crs_selfcheck_fail=0

# 伪造 A:删掉 1 行 Scrapy + 3 行其它标准(评审 R-02 点名的误通过场景)
awk 'NR==FNR{next}{print}' /dev/null "$tmp/rs.v100" \
  | grep -vF -- '- Scrapy:阻塞调用混入 reactor/事件循环、selector 取值无防御(裸下标/' \
  | grep -vF -- '- TypeScript:类型逃逸(as any / @ts-ignore)、未处理的 Promise、状态管理一致性' \
  | grep -vF -- '- Python/FastAPI:阻塞调用混入 async 路径、Pydantic 校验缺失、异常吞噬' \
  | grep -vF -- '- 通用:plan 中测试用例是否被偷工减料(只测 happy path 即 major)' \
  > "$tmp/rs.fakeA"
note "  伪造 A(删 1 行 Scrapy + 3 行其它标准,共 4 行):"
if CRS_SILENT=1 check_review_standards "$tmp/rs.v100" "$tmp/rs.fakeA" >/dev/null 2>&1; then
  bad "反向自检失效:伪造 A 竟然通过 D-1 断言(旧的"含 Scrapy 即可"逻辑残留)"
  crs_selfcheck_fail=1
else
  note "  OK  伪造 A 被拒(逐字节断言生效)"
fi

# 伪造 B:删掉完整的 Scrapy 4 行块,但把其中 1 行替换为改写版后留下
sed 's/item 静默丢失、去重\/限速\/重试配置被关闭或绕过、解析测试依赖真网/item 静默丢失(本行被改写)/' \
  "$tmp/rs.v100" > "$tmp/rs.tmpB"
grep -vF -- '- Scrapy:阻塞调用混入 reactor/事件循环、selector 取值无防御(裸下标/' "$tmp/rs.tmpB" \
  | grep -vF -- '  无 default 导致页面结构变化即崩)、pipeline/middleware 异常吞噬致' \
  | grep -vF -- '  (须用本地 fixture 响应)' > "$tmp/rs.fakeB"
note "  伪造 B(删掉整块 4 行,但把其中 1 行改写后留在原处 —— 应同时触发"有新增行"与逐字节不等):"
if CRS_SILENT=1 check_review_standards "$tmp/rs.v100" "$tmp/rs.fakeB" >/dev/null 2>&1; then
  bad "反向自检失效:伪造 B 竟然通过 D-1 断言"
  crs_selfcheck_fail=1
else
  note "  OK  伪造 B 被拒(逐字节断言生效)"
fi

[ "$crs_selfcheck_fail" -eq 0 ] && note "  反向自检结论:D-1 断言不是恒真通过"

note ""
note "== 6. 计数汇总(脚本现算,非预写死)=="
note "  IDENTICAL       : $n_identical"
note "  EXPECTED-DIFF   : $n_expdiff"
note "  EXPECTED-ABSENT : $n_expabsent"
note "  UNEXPECTED-*    : $n_unexpected"

if [ "$fail" -eq 0 ]; then
  note ""
  note "RESULT: PASS —— 可整体替换类已完成对 v1.0.0 的全量基线对齐"
else
  note ""
  note "RESULT: FAIL"
fi
exit "$fail"
