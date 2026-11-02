#!/usr/bin/env bash
# TC-07:0020 修订小节、D-6、钉死 SHA 与索引行;两文件内相对链接可解析。
set -uo pipefail
repo=$(git rev-parse --show-toplevel)
d="$repo/docs/decisions/0020-ai-workflow-template-version-anchor.md"
idx="$repo/docs/decisions/README.md"
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }
has() { grep -qF -- "$2" "$1" && ok "${1##*/} 含:$2" || bad "${1##*/} 缺:$2"; }

has "$d" '## 修订'
has "$d" '2026-11-02:**升至 v1.2.1**'
has "$d" '`v1.0.0` = `2aeab2eaca28b1364a46ec7cfc9195849cc61b68`'
has "$d" '`246db2af223f4279f2ddc3773c5c3171dc8096cc`'
has "$d" '| D-6 | `CLAUDE.md` / `.gitignore` |'
has "$d" '`version: 1.2.1` / `adopted: 2026-11-02`'
has "$d" '.ai/2026-11-02/upgrade-ai-workflow-template-v1-2-1/evidence/'
# 既有偏离 D-1~D-5 未被删改
for k in D-1 D-2 D-3 D-4 D-5; do
  grep -qE "^    \| $k \|" "$d" && ok "既有偏离 $k 仍在" || bad "既有偏离 $k 丢失"
done
# 修订小节只追加:HEAD 版本是当前文件的前缀
if git -C "$repo" show HEAD:docs/decisions/0020-ai-workflow-template-version-anchor.md > /tmp/.0020-head.$$; then
  n=$(wc -c < /tmp/.0020-head.$$)
  if cmp -s /tmp/.0020-head.$$ <(head -c "$n" "$d"); then ok "0020 既有正文未改动(只追加)"; else bad "0020 既有正文被改动"; fi
  rm -f /tmp/.0020-head.$$
fi
has "$idx" '| [0020](0020-ai-workflow-template-version-anchor.md) | 认领 ai-workflow-template v1.0.0 版本锚点；不采用其 Scrapy 标准栈(2026-11-02 升至 v1.2.1) |'

# 相对链接可解析(markdown 链接中非 http、非锚点的目标)
for f in "$d" "$idx"; do
  while IFS= read -r link; do
    target=${link%%#*}
    [ -z "$target" ] && continue
    if [ -e "$(dirname "$f")/$target" ]; then ok "${f##*/} 链接可解析:$target"
    else bad "${f##*/} 链接不可解析:$target"; fi
  done < <(grep -oE '\]\([^)]+\)' "$f" | sed -E 's/^\]\(//; s/\)$//' | grep -vE '^(https?:|mailto:|#)' | sort -u)
done

echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
