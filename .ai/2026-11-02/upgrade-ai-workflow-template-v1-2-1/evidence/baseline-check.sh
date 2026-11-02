#!/usr/bin/env bash
# TC-01:可整体替换类受管路径对模板 v1.2.1 的全量基线核验(双向)。
# 用法:baseline-check.sh <模板克隆路径>
# 路径集不手写:由 v1.2.1 的 git ls-tree 按 CHANGELOG「可整体替换」六条 glob 现算。
# 例外表只有 3 条(见 plan「实现方案」第 5 步),其余必须 IDENTICAL。
set -uo pipefail
export LC_ALL=C

tpl=${1:?用法:baseline-check.sh <模板克隆路径>}
repo=$(git rev-parse --show-toplevel)
PIN_NEW=246db2af223f4279f2ddc3773c5c3171dc8096cc
PIN_OLD=2aeab2eaca28b1364a46ec7cfc9195849cc61b68

new=$(git -C "$tpl" rev-parse 'v1.2.1^{commit}')
old=$(git -C "$tpl" rev-parse 'v1.0.0^{commit}')
echo "模板 v1.2.1 = $new(钉死 $PIN_NEW)"
echo "模板 v1.0.0 = $old(钉死 $PIN_OLD)"
if [ "$new" != "$PIN_NEW" ] || [ "$old" != "$PIN_OLD" ]; then
  echo "FAIL:tag 解析结果与钉死 SHA 不符"; exit 1
fi

# CHANGELOG 头部「可整体替换」:.ai-workflow/、.claude/hooks/、.claude/skills/rawf-*、
# .claude/settings.json、.githooks/、.gitmessage
managed_re='^(\.ai-workflow/|\.claude/hooks/|\.claude/skills/rawf-[^/]+/|\.claude/settings\.json$|\.githooks/|\.gitmessage$)'

mapfile -t tpl_paths < <(git -C "$tpl" ls-tree -r --name-only "$PIN_NEW" | grep -E "$managed_re" | sort)
mapfile -t loc_paths < <( { git -C "$repo" ls-files; git -C "$repo" ls-files --others --exclude-standard; } \
  | grep -E "$managed_re" | sort -u)

declare -A in_tpl
for p in "${tpl_paths[@]}"; do in_tpl[$p]=1; done

declare -A cnt=([IDENTICAL]=0 [EXPECTED-DIFF]=0 [EXPECTED-ABSENT]=0 [UNEXPECTED-DIFF]=0 [UNEXPECTED-ABSENT]=0 [UNEXPECTED-EXTRA]=0 [UNEXPECTED-MODE]=0)
verdict() { cnt[$1]=$(( ${cnt[$1]} + 1 )); printf '%-18s %s\n' "$1" "$2"; }

tplsha() { git -C "$tpl" show "$PIN_NEW:$1" | sha256sum | cut -d' ' -f1; }
locsha() { sha256sum < "$repo/$1" | cut -d' ' -f1; }

# D-1:Scrapy 关注点 4 行块(以 "- Scrapy:" 起头的连续 4 行)
scrapy_block() { awk '/^- Scrapy:/ { n = 4 } n > 0 { print; n-- }'; }

check_template_version() {
  local p=.ai-workflow/TEMPLATE-VERSION
  local t l
  t=$(git -C "$tpl" show "$PIN_NEW:$p"); l=$(cat "$repo/$p")
  local tl ll
  tl=$(printf '%s\n' "$t" | wc -l); ll=$(printf '%s\n' "$l" | wc -l)
  if [ "$tl" = "$ll" ] \
     && [ "$(printf '%s\n' "$t" | sed -n '1,2p')" = "$(printf '%s\n' "$l" | sed -n '1,2p')" ] \
     && [ "$(printf '%s\n' "$l" | sed -n '3p')" = "adopted: 2026-11-02" ]; then
    echo "  第 1-2 行与模板一致:$(printf '%s\n' "$l" | sed -n '1p') / $(printf '%s\n' "$l" | sed -n '2p')"
    echo "  第 3 行 = '$(printf '%s\n' "$l" | sed -n '3p')'"
    verdict EXPECTED-DIFF "$p"
  else
    verdict UNEXPECTED-DIFF "$p(TEMPLATE-VERSION 断言不成立)"
  fi
}

check_review_standards() {
  local p=.ai-workflow/review-standards.md
  local b_new b_old
  b_new=$(git -C "$tpl" show "$PIN_NEW:$p" | scrapy_block)
  b_old=$(git -C "$tpl" show "$PIN_OLD:$p" | scrapy_block)
  local n_heads
  n_heads=$(git -C "$tpl" show "$PIN_NEW:$p" | grep -c '^- Scrapy:')
  echo "  v1.2.1 中 '- Scrapy:' 起头行数 = $n_heads;D-1 块行数 = $(printf '%s\n' "$b_new" | wc -l)"
  echo "  D-1 块(v1.2.1 侧):"; printf '%s\n' "$b_new" | sed 's/^/    | /'
  if [ "$n_heads" != 1 ] || [ "$b_new" != "$b_old" ]; then
    verdict UNEXPECTED-DIFF "$p(D-1 块在 v1.0.0 与 v1.2.1 间不一致或不唯一)"; return
  fi
  local expect_sha
  expect_sha=$(git -C "$tpl" show "$PIN_NEW:$p" | awk '/^- Scrapy:/ { n = 4 } n > 0 { n--; next } { print }' | sha256sum | cut -d' ' -f1)
  local got_sha; got_sha=$(locsha "$p")
  echo "  期望(v1.2.1 删去 D-1 块)sha256 = $expect_sha"
  echo "  本仓库                   sha256 = $got_sha"
  if [ "$expect_sha" = "$got_sha" ]; then verdict EXPECTED-DIFF "$p"
  else verdict UNEXPECTED-DIFF "$p(不等于 v1.2.1 删去 D-1 块)"; fi
}

for p in "${tpl_paths[@]}"; do
  case "$p" in
    .ai-workflow/TEMPLATE-VERSION) check_template_version; continue ;;
    .ai-workflow/review-standards.md) check_review_standards; continue ;;
    .claude/skills/rawf-stack-scrapy/SKILL.md)
      if [ -e "$repo/$p" ]; then verdict UNEXPECTED-DIFF "$p(D-4:不应存在)"
      else verdict EXPECTED-ABSENT "$p(D-4)"; fi
      continue ;;
  esac
  if [ ! -f "$repo/$p" ]; then verdict UNEXPECTED-ABSENT "$p"; continue; fi
  ts=$(tplsha "$p"); ls_=$(locsha "$p")
  mode=$(git -C "$tpl" ls-tree "$PIN_NEW" -- "$p" | awk '{print $1}')
  if [ "$mode" = 100755 ] && [ ! -x "$repo/$p" ]; then verdict UNEXPECTED-MODE "$p(模板 100755,本地不可执行)"; continue; fi
  if [ "$ts" = "$ls_" ]; then verdict IDENTICAL "$p  sha256=$ts"
  else verdict UNEXPECTED-DIFF "$p  tpl=$ts loc=$ls_"; fi
done

for p in "${loc_paths[@]}"; do
  [ -n "${in_tpl[$p]:-}" ] || verdict UNEXPECTED-EXTRA "$p"
done

echo
echo "== 汇总 =="
for k in IDENTICAL EXPECTED-DIFF EXPECTED-ABSENT UNEXPECTED-DIFF UNEXPECTED-ABSENT UNEXPECTED-EXTRA UNEXPECTED-MODE; do
  printf '%-18s %d\n' "$k" "${cnt[$k]}"
done
bad=$(( ${cnt[UNEXPECTED-DIFF]} + ${cnt[UNEXPECTED-ABSENT]} + ${cnt[UNEXPECTED-EXTRA]} + ${cnt[UNEXPECTED-MODE]} ))
if [ "$bad" -ne 0 ] || [ "${cnt[EXPECTED-DIFF]}" -ne 2 ] || [ "${cnt[EXPECTED-ABSENT]}" -ne 1 ]; then
  echo "RESULT: FAIL"; exit 1
fi
echo "RESULT: PASS"
