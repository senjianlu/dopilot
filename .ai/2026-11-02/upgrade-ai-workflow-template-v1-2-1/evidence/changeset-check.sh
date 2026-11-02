#!/usr/bin/env bash
# TC-08:变更集恰为 plan 列出的 23 个文件 ∪ 本任务目录;应用代码零改动;
# 既有未跟踪建议目录内容不变(只打印文件数与清单整体 sha256,不打印路径——
# 该目录含业务信息)。
set -uo pipefail
export LC_ALL=C
repo=$(git rev-parse --show-toplevel)
cd "$repo" || exit 3
task=.ai/2026-11-02/upgrade-ai-workflow-template-v1-2-1
sugg=.ai/2026-11-02/transient-failures-permanent-disable
baseline=/tmp/claude-1000/awt/untracked-baseline.sha256
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }

expected=$(sort <<'EOF'
.ai-workflow/TEMPLATE-VERSION
.ai-workflow/prompts/plan-review.md
.ai-workflow/prompts/review.md
.ai-workflow/review-standards.md
.ai-workflow/schemas/plan-review.schema.json
.ai-workflow/schemas/review.schema.json
.ai-workflow/scripts/evidence-check.sh
.ai-workflow/scripts/evidence.sh
.ai-workflow/scripts/plan-review.sh
.ai-workflow/scripts/review.sh
.ai-workflow/templates/implementation-round.md
.ai-workflow/templates/plan.md
.ai-workflow/templates/summary.md
.claude/hooks/gate-review.sh
.claude/skills/rawf-implement/SKILL.md
.claude/skills/rawf-plan/SKILL.md
.claude/skills/rawf-report/SKILL.md
.claude/skills/rawf-review/SKILL.md
.gitignore
AGENTS.md
CLAUDE.md
docs/decisions/0020-ai-workflow-template-version-anchor.md
docs/decisions/README.md
EOF
)
echo "plan 列出文件数:$(printf '%s\n' "$expected" | wc -l)"

# 实际变更:已跟踪改动 + 未跟踪文件(逐文件展开),剔除本任务目录与建议目录
actual_all=$( { git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u)
actual=$(printf '%s\n' "$actual_all" | grep -v -E "^($task|$sugg)/" | sed '/^$/d')
echo "实际变更(除本任务目录与建议目录):$(printf '%s\n' "$actual" | wc -l) 个"
printf '%s\n' "$actual" | sed 's/^/  /'

missing=$(comm -23 <(printf '%s\n' "$expected") <(printf '%s\n' "$actual"))
extra=$(comm -13 <(printf '%s\n' "$expected") <(printf '%s\n' "$actual"))
[ -z "$missing" ] && ok "plan 列出的 23 个文件全部有改动" || { bad "plan 列出但未改动:"; printf '  %s\n' $missing; }
[ -z "$extra" ] && ok "无 plan 之外的改动" || { bad "plan 之外的改动:"; printf '  %s\n' $extra; }

app=$(printf '%s\n' "$actual_all" | grep -E '^(apps|packages|deploy|configs|scripts|examples|tests)/' || true)
[ -z "$app" ] && ok "apps/ packages/ deploy/ configs/ scripts/ examples/ tests/ 零改动" || { bad "应用路径有改动"; printf '  %s\n' $app; }

# 本任务目录内只有任务产物
others=$(printf '%s\n' "$actual_all" | grep -E "^$task/" | grep -v -E "^$task/(plan\.md|plan-review-round-[0-9]+-(pass|fail)\.md|implementation-round-[0-9]+\.md|review-round-[0-9]+-(pass|fail)\.md|summary\.md|evidence/.+|assets/.+)$" || true)
[ -z "$others" ] && ok "本任务目录只含任务产物" || { bad "本任务目录含非产物文件"; printf '  %s\n' $others; }

# 建议目录:内容与任务开始时的清单一致(只报数量与整体哈希)
if [ -f "$baseline" ]; then
  # 两侧都按 LC_ALL=C 逐行重排后再取整体哈希,与清单生成时的 locale 无关
  now=$(cd "$sugg" && find . -type f -print0 | xargs -0 sha256sum | sort)
  b_sum=$(sort < "$baseline" | sha256sum | cut -d' ' -f1); n_sum=$(printf '%s\n' "$now" | sha256sum | cut -d' ' -f1)
  echo "建议目录:基线 $(wc -l < "$baseline") 个文件 清单 sha256=$b_sum;当前 $(printf '%s\n' "$now" | wc -l) 个 清单 sha256=$n_sum"
  [ "$b_sum" = "$n_sum" ] && ok "建议目录内容未变" || bad "建议目录内容有变化"
  git ls-files --error-unmatch "$sugg" >/dev/null 2>&1 && bad "建议目录被纳入跟踪" || ok "建议目录仍未跟踪"
else
  bad "缺少仓库外基线清单 $baseline"
fi

echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
