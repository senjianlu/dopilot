#!/usr/bin/env bash
# TC-02:需人工合并类(CLAUDE.md / AGENTS.md / .gitignore)逐 hunk 断言。
# CLAUDE.md 另做整文件等价断言:模板 v1.2.1 原文经 D-2(删 0003 尾注行)与
# D-6("见 docs/decisions/00NN"→"见模板决策 00NN",其余 docs/decisions/00NN → 模板决策 00NN,
# NN ∈ 09~12)规范化后,须与本仓库逐字节相等。
set -uo pipefail
export LC_ALL=C
repo=$(git rev-parse --show-toplevel)
tpl=${TPL:-/tmp/claude-1000/awt/tpl}
PIN_NEW=246db2af223f4279f2ddc3773c5c3171dc8096cc
fail=0
pass() { echo "PASS  $1"; }
bad()  { echo "FAIL  $1"; fail=1; }

has()  { grep -qF -- "$2" "$repo/$1" && pass "$1 含:$2" || bad "$1 缺:$2"; }
hasnt(){ grep -qF -- "$2" "$repo/$1" && bad "$1 仍含:$2" || pass "$1 不含:$2"; }

# --- CLAUDE.md ---
has CLAUDE.md '默认最多 5 轮(第 1、2 轮全量'
has CLAUDE.md '穷尽、第 3 轮起收敛;用户明确指定时以其为准,见硬规则),不决转人工'
has CLAUDE.md '**评审轮次上限默认值:plan 评审 5 轮、实现层修复 3 轮**(各自计数;'
has CLAUDE.md 'plan 评审默认值见模板决策 0012),仅当'
has CLAUDE.md '**A 档证据一律经 `.ai-workflow/scripts/evidence.sh` 留证**(rawf-evidence'
has CLAUDE.md '格式问题由机器判定(模板决策 0010)'
has CLAUDE.md '**追加类偏差不得自行实现**:plan 范围之外的新增文件、行为、功能,要么'
has CLAUDE.md '原样交用户裁决(模板决策 0011)'
hasnt CLAUDE.md 'plan 再重评,默认最多 3 轮'
has CLAUDE.md '实现层修复默认最多 3 轮'
hasnt CLAUDE.md '评审轮次上限默认均为 3 轮'
hasnt CLAUDE.md '(机制见 docs/decisions/0003)'
for f in CLAUDE.md .gitignore; do
  if grep -nE 'docs/decisions/00(09|10|11|12)' "$repo/$f"; then bad "$f 存在裸的模板决策路径引用(D-6)"
  else pass "$f 无裸的 docs/decisions/0009~0012 引用(D-6)"; fi
done
norm_sha=$(git -C "$tpl" show "$PIN_NEW:CLAUDE.md" \
  | grep -vF '(机制见 docs/decisions/0003)' \
  | sed -E 's#见 docs/decisions/00(09|10|11|12)#见模板决策 00\1#g; s#docs/decisions/00(09|10|11|12)#模板决策 00\1#g' \
  | sha256sum | cut -d' ' -f1)
loc_sha=$(sha256sum < "$repo/CLAUDE.md" | cut -d' ' -f1)
echo "      CLAUDE.md 规范化模板 sha256=$norm_sha"
echo "      CLAUDE.md 本仓库     sha256=$loc_sha"
[ "$norm_sha" = "$loc_sha" ] && pass "CLAUDE.md = 模板 v1.2.1 经 D-2/D-6 规范化(整文件等价)" \
  || bad "CLAUDE.md 与规范化模板不等价"

# --- AGENTS.md ---
has AGENTS.md '先经 plan 阶段 Codex 评审(plan-review,默认最多 5 轮,用户明确指定'
hasnt AGENTS.md '默认最多 3 轮'

# --- .gitignore:rawf 块三行紧随 .plan-review-out-* 之后 ---
blk=$(grep -n -A3 -F '.ai/**/.plan-review-out-*' "$repo/.gitignore")
echo "      .gitignore 片段:"; printf '%s\n' "$blk" | sed 's/^/        /'
expect=$'.ai/**/.plan-review-out-*\n# rawf:评审 flock 锁文件(常驻任务目录,永不删除;锁语义见模板决策 0009)\n.ai/**/.review-lock\n.ai/**/.plan-review-lock'
got=$(grep -A3 -F '.ai/**/.plan-review-out-*' "$repo/.gitignore")
[ "$got" = "$expect" ] && pass ".gitignore 锁文件两行及注释紧随 rawf 块" || bad ".gitignore rawf 锁文件块不符"
# 锁文件确实被忽略
git -C "$repo" check-ignore -q .ai/2026-11-02/x/.review-lock && pass ".review-lock 被忽略" || bad ".review-lock 未被忽略"
git -C "$repo" check-ignore -q .ai/2026-11-02/x/.plan-review-lock && pass ".plan-review-lock 被忽略" || bad ".plan-review-lock 未被忽略"

echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
