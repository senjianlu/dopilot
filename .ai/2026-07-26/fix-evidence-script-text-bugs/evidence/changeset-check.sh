#!/usr/bin/env bash
# TC-05:改动集边界断言,并**专项断言两份历史证据未被重新生成**。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail

TD=.ai/2026-07-26/fix-evidence-script-text-bugs
# 用户 2026-07-26 裁决:只修脚本,不重生成历史证据。这两份输出必须保持
# 未修改状态——它们记录的是当时评审实际看到的内容。
HIST_A=.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc05-decision-docs.txt
HIST_B=.ai/2026-07-26/ci-docker-login-before-buildx/evidence/tc03-reverse-selfcheck.txt
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== 1. git status --porcelain --untracked-files=all 原始输出 =="
git status --porcelain --untracked-files=all | sed 's/^/  /'
actual=$(git status --porcelain --untracked-files=all | sed 's/^...//' | sed 's/^"//; s/"$//' | sort -u)

declared_src=$(cat <<'EOF'
.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh
.ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh
EOF
)

note ""
note "== 2. 源文件改动:与 plan 声明清单做集合相等断言 =="
actual_src=$(printf '%s\n' "$actual" | grep -v "^$TD/" | sort -u)
note "  实际(排除本任务 .ai/ 产物):"; printf '%s\n' "$actual_src" | sed 's/^/    /'
note "  plan 声明:"; printf '%s\n' "$declared_src" | sort | sed 's/^/    /'
only_actual=$(comm -23 <(printf '%s\n' "$actual_src") <(printf '%s\n' "$declared_src" | sort))
only_declared=$(comm -13 <(printf '%s\n' "$actual_src") <(printf '%s\n' "$declared_src" | sort))
[ -n "$only_actual" ] && { printf '%s\n' "$only_actual" | sed 's/^/  UNDECLARED  /'; bad "存在 plan 未声明却被改动的文件"; }
[ -n "$only_declared" ] && { printf '%s\n' "$only_declared" | sed 's/^/  NOT-CHANGED /'; bad "plan 声明要改却未改动的文件"; }
[ -z "$only_actual" ] && [ -z "$only_declared" ] && ok "集合相等:恰好 2 个脚本"

note ""
note "== 3. 【专项】两份历史证据必须保持未修改 =="
for h in "$HIST_A" "$HIST_B"; do
  if printf '%s\n' "$actual" | grep -qFx "$h"; then
    bad "$h 出现在改动集中 —— 违反"不重新生成历史证据"的用户裁决"
  else
    ok "$h 未被改动"
  fi
  # 再以 git diff 双保险:即便 status 因故漏报,内容变化也会被 diff 抓到
  if git diff --quiet -- "$h" 2>/dev/null; then
    note "      git diff 确认无内容变化"
  else
    bad "$h 的 git diff 非空,内容已被改动"
  fi
done

note ""
note "== 4. 明确不动的目录/文件必须零改动 =="
for d in apps packages deploy configs scripts examples tests docs .github .ai-workflow .claude .agents .githooks; do
  hits=$(printf '%s\n' "$actual" | grep "^$d/" || true)
  if [ -z "$hits" ]; then
    ok "$d/ 零改动"
  else
    printf '%s\n' "$hits" | sed 's/^/    /'
    bad "$d/ 存在改动,违反 plan「明确不动」"
  fi
done
for f in AGENTS.md CLAUDE.md README.md README.zh-CN.md .gitignore .gitmessage skills-lock.json; do
  printf '%s\n' "$actual" | grep -qFx "$f" && bad "$f 被改动,违反 plan「明确不动」" || ok "$f 零改动"
done

note ""
note "== 5. 两个来源任务的轮次记录必须零改动 =="
for t in align-ai-workflow-template-v1 ci-docker-login-before-buildx; do
  hits=$(printf '%s\n' "$actual" | grep -E "^\.ai/2026-07-26/$t/(plan|implementation-round|review-round|plan-review-round|summary)" || true)
  if [ -z "$hits" ]; then
    ok "$t 的 plan / 轮次记录 / summary 零改动"
  else
    printf '%s\n' "$hits" | sed 's/^/    /'
    bad "$t 的轮次记录被改动,违反「只增不改」"
  fi
done

note ""
note "== 6. 本任务目录产物一览 =="
printf '%s\n' "$actual" | grep "^$TD/" | sed 's/^/  /'

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
