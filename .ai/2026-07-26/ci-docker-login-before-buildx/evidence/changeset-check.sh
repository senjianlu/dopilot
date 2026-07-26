#!/usr/bin/env bash
# TC-04:改动集边界断言——git status 的改动集必须与 plan「改动范围」声明的
# 清单**集合相等**(不是"包含"),反向证明"明确不动"的部分确实没动。
# 用法(cwd 必须是仓库根):bash <本脚本>
#
# 注:必须用 --untracked-files=all。默认 --porcelain 会把整个未跟踪目录折叠
# 成一行(如 `.ai/2026-07-26/`),按任务目录前缀过滤会漏掉全部产物。
set -uo pipefail

TD=.ai/2026-07-26/ci-docker-login-before-buildx
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== 1. git status --porcelain --untracked-files=all 原始输出 =="
git status --porcelain --untracked-files=all | sed 's/^/  /'
actual=$(git status --porcelain --untracked-files=all | sed 's/^...//' | sed 's/^"//; s/"$//' | sort -u)

declared_src=".github/workflows/docker.yml"

note ""
note "== 2. 源文件改动:与 plan 声明清单做集合相等断言 =="
actual_src=$(printf '%s\n' "$actual" | grep -v "^$TD/" | sort -u)
note "  实际(排除本任务 .ai/ 产物):"; printf '%s\n' "$actual_src" | sed 's/^/    /'
note "  plan 声明:"; printf '%s\n' "$declared_src" | sed 's/^/    /'
only_actual=$(comm -23 <(printf '%s\n' "$actual_src") <(printf '%s\n' "$declared_src" | sort))
only_declared=$(comm -13 <(printf '%s\n' "$actual_src") <(printf '%s\n' "$declared_src" | sort))
[ -n "$only_actual" ] && { printf '%s\n' "$only_actual" | sed 's/^/  UNDECLARED  /'; bad "存在 plan 未声明却被改动的文件"; }
[ -n "$only_declared" ] && { printf '%s\n' "$only_declared" | sed 's/^/  NOT-CHANGED /'; bad "plan 声明要改却未改动的文件"; }
[ -z "$only_actual" ] && [ -z "$only_declared" ] && ok "集合相等:恰好 1 个源文件"

note ""
note "== 3. 明确不动的目录/文件必须零改动 =="
for d in apps packages deploy configs scripts examples tests docs .ai-workflow .claude .agents .githooks; do
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
note "== 4. 本任务目录产物一览 =="
printf '%s\n' "$actual" | grep "^$TD/" | sed 's/^/  /'

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
