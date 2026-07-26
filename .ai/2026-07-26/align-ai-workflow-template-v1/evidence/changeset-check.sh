#!/usr/bin/env bash
# TC-07:改动集边界断言——git status 的改动集必须与 plan「改动范围」声明的
# 清单**集合相等**(不是"包含"),反向证明"明确不动"的部分确实没动。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail

TD=.ai/2026-07-26/align-ai-workflow-template-v1
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

# 注:必须用 --untracked-files=all。默认的 --porcelain 会把整个未跟踪目录
# 折叠成一行(如 `.ai/2026-07-26/`),按任务目录前缀过滤会漏掉全部产物,
# 导致集合相等断言误报。
note "== 1. git status --porcelain --untracked-files=all 原始输出 =="
git status --porcelain --untracked-files=all | sed 's/^/  /'

# 实际改动集(去掉状态位;含未跟踪文件)
actual=$(git status --porcelain --untracked-files=all | sed 's/^...//' | sed 's/^"//; s/"$//' | sort -u)

# plan 声明的 4 个受管/文档文件
declared_src=$(cat <<'EOF'
.ai-workflow/TEMPLATE-VERSION
docs/decisions/0020-ai-workflow-template-version-anchor.md
docs/decisions/README.md
docs/decisions/0018-adopt-ai-workflow-template.md
EOF
)

note ""
note "== 2. 受管/文档改动:与 plan 声明清单做集合相等断言 =="
actual_src=$(printf '%s\n' "$actual" | grep -v "^$TD/" | sort -u)
note "  实际(排除本任务 .ai/ 产物):"
printf '%s\n' "$actual_src" | sed 's/^/    /'
note "  plan 声明:"
printf '%s\n' "$declared_src" | sort | sed 's/^/    /'

only_actual=$(comm -23 <(printf '%s\n' "$actual_src") <(printf '%s\n' "$declared_src" | sort))
only_declared=$(comm -13 <(printf '%s\n' "$actual_src") <(printf '%s\n' "$declared_src" | sort))
if [ -n "$only_actual" ]; then
  printf '%s\n' "$only_actual" | sed 's/^/  UNDECLARED  /'
  bad "存在 plan 未声明却被改动的文件"
fi
if [ -n "$only_declared" ]; then
  printf '%s\n' "$only_declared" | sed 's/^/  NOT-CHANGED /'
  bad "plan 声明要改却未改动的文件"
fi
[ -z "$only_actual" ] && [ -z "$only_declared" ] && ok "集合相等:恰好 4 个受管/文档文件"

note ""
note "== 3. 其余改动必须全部落在本任务目录内 =="
outside=$(printf '%s\n' "$actual" | grep -v "^$TD/" | grep -vFx -f <(printf '%s\n' "$declared_src") || true)
if [ -z "$outside" ]; then
  ok "无越界改动"
else
  printf '%s\n' "$outside" | sed 's/^/  OUTSIDE  /'
  bad "存在既不在声明清单、也不在任务目录内的改动"
fi

note ""
note "== 4. 明确不动的目录必须零改动 =="
for d in apps packages deploy configs scripts examples tests .github .githooks .agents; do
  hits=$(printf '%s\n' "$actual" | grep "^$d/" || true)
  if [ -z "$hits" ]; then
    ok "$d/ 零改动"
  else
    printf '%s\n' "$hits" | sed 's/^/    /'
    bad "$d/ 存在改动,违反 plan「明确不动」"
  fi
done
for f in AGENTS.md CLAUDE.md README.md README.zh-CN.md .gitignore .gitmessage skills-lock.json; do
  if printf '%s\n' "$actual" | grep -qFx "$f"; then
    bad "$f 被改动,违反 plan「明确不动」"
  else
    ok "$f 零改动"
  fi
done

note ""
note "== 5. 本任务目录产物一览 =="
printf '%s\n' "$actual" | grep "^$TD/" | sed 's/^/  /'

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
