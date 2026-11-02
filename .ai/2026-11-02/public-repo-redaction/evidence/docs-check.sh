#!/usr/bin/env bash
# TC-08:决策 0024、索引、AGENTS.md、0020 D-7、CONTRIBUTING、架构目录树、pyproject。
set -uo pipefail
repo=$(git rev-parse --show-toplevel); cd "$repo" || exit 3
d=docs/decisions/0024-public-repo-redaction.md
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }
has() { grep -qF -- "$2" "$1" && ok "$1 含:$2" || bad "$1 缺:$2"; }

[ -f "$d" ] && ok "$d 存在" || bad "$d 不存在"
for k in '- 日期:2026-11-02' '- 背景:' '- 决定:' '- 影响:' \
         '① 目标站点与数据源' '② 下游项目与业务' '③ 业务对象' '④ 生产基础设施' '⑤ 凭据' '⑥ 原始生产数据' \
         '**`.ai/` 只增不改的例外**' '**别名对照只存在私有规则文件里**' 'fail-closed' 'DOPILOT_REDACTION_RULES=none'; do
  has "$d" "$k"
done
has docs/decisions/README.md '| [0024](0024-public-repo-redaction.md) |'
has AGENTS.md '公开仓库脱敏'
has AGENTS.md 'docs/decisions/0024'
has AGENTS.md '脱敏改写除外'
has docs/README.md 'decisions/0024'
has CONTRIBUTING.md 'pre-commit'
has CONTRIBUTING.md 'pre-push'
has CONTRIBUTING.md 'DOPILOT_REDACTION_RULES=none'
has docs/architecture/README.md 'redaction'
has pyproject.toml '"scripts/redaction/tests",'
z=docs/decisions/0020-ai-workflow-template-version-anchor.md
has "$z" '| D-7 |'
# 0020 只追加:HEAD 版本是当前文件的前缀
n=$(git show HEAD:"$z" | wc -c)
if cmp -s <(git show HEAD:"$z") <(head -c "$n" "$z"); then ok "0020 既有正文未改(只追加)"; else bad "0020 既有正文被改"; fi
# 相对链接
for f in "$d" docs/decisions/README.md "$z"; do
  while IFS= read -r link; do
    t=${link%%#*}; [ -z "$t" ] && continue
    [ -e "$(dirname "$f")/$t" ] && ok "${f##*/} 链接可解析:$t" || bad "${f##*/} 链接不可解析:$t"
  done < <(grep -oE '\]\([^)]+\)' "$f" | sed -E 's/^\]\(//; s/\)$//' | grep -vE '^(https?:|mailto:|#)' | sort -u)
done
echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
