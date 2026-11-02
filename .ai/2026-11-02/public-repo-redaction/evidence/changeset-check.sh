#!/usr/bin/env bash
# TC-09:变更集 = A 表新增 7 + B 表修改 7 + C 节 52 个路径(按 HEAD 路径计)+ 本任务目录;
# apps/ 只动 C 节 5 个文件;未跟踪建议目录内容未变且仍未跟踪。只打印计数与非敏感路径。
set -uo pipefail
export LC_ALL=C
repo=$(git rev-parse --show-toplevel); cd "$repo" || exit 3
task=.ai/2026-11-02/public-repo-redaction
sugg=.ai/2026-11-02/transient-failures-permanent-disable
baseline=/tmp/claude-1000/awt/untracked-baseline.sha256
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }

new_expected=$(sort <<'L'
.githooks/pre-commit
.githooks/pre-push
docs/decisions/0024-public-repo-redaction.md
scripts/redaction/generic-rules.tsv
scripts/redaction/redact.py
scripts/redaction/rewrite_history.py
scripts/redaction/tests/test_redact.py
L
)
manual=$(sort <<'L'
AGENTS.md
CONTRIBUTING.md
docs/README.md
docs/architecture/README.md
docs/decisions/0020-ai-workflow-template-version-anchor.md
docs/decisions/README.md
pyproject.toml
L
)
apps_expected=$(sort <<'L'
apps/agent/tests/test_logcap.py
apps/agent/tests/test_scrapyd_stats.py
apps/web/app/(app)/schedules/__tests__/schedules.test.tsx
apps/web/app/(app)/schedules/page.tsx
apps/web/components/layout/__tests__/notification-bell.test.tsx
L
)
untracked=$(git ls-files --others --exclude-standard | grep -v -E "^($task|$sugg)/" | sort)
[ "$untracked" = "$new_expected" ] && ok "新增文件恰为 A 表 7 个" || { bad "新增文件与 A 表不符"; diff <(echo "$new_expected") <(echo "$untracked"); }

ns=$(git diff --name-status --no-renames HEAD | grep -v -E "	($task)/")
M=$(printf '%s\n' "$ns" | awk -F'\t' '$1=="M"{print $2}' | sort)
D=$(printf '%s\n' "$ns" | awk -F'\t' '$1=="D"{print $2}' | sort)
A=$(printf '%s\n' "$ns" | awk -F'\t' '$1=="A"{print $2}' | sort)
nM=$(printf '%s\n' "$M" | sed '/^$/d' | wc -l); nD=$(printf '%s\n' "$D" | sed '/^$/d' | wc -l); nA=$(printf '%s\n' "$A" | sed '/^$/d' | wc -l)
echo "      相对 HEAD:修改 $nM、删除(改名旧路径)$nD、新增(改名新路径)$nA"
[ -z "$(comm -23 <(echo "$manual") <(echo "$M"))" ] && ok "B 表 7 个文件均有修改" || bad "B 表有文件未修改"
c_count=$(( nM - 7 + nD ))
[ "$c_count" -eq 52 ] && ok "C 节路径数 = 52(修改 $((nM - 7)) + 改名 $nD)" || bad "C 节路径数 $c_count ≠ 52"
[ "$nD" -eq 2 ] && [ "$nA" -eq 2 ] && ok "改名 2 个(旧路径删除、新路径新增各 2)" || bad "改名数不符"
apps=$(printf '%s\n%s\n%s\n' "$M" "$D" "$A" | grep '^apps/' | sort -u)
[ "$apps" = "$apps_expected" ] && ok "apps/ 只改 C 节 5 个文件" || { bad "apps/ 改动不符"; echo "$apps"; }
other=$(printf '%s\n%s\n%s\n' "$M" "$D" "$A" | sed '/^$/d' | grep -v -E '^(\.ai/|apps/|docs/)' | sort -u)
[ "$other" = "$(printf '%s\n' "$manual" | grep -v -E '^(docs/)')" ] && ok "仓库根与其它目录只改 B 表文件" || { bad "存在计划外改动"; echo "$other"; }
docs_c=$(printf '%s\n' "$M" | grep '^docs/' | grep -v -x -F -f <(echo "$manual") | sort)
[ "$(printf '%s\n' "$docs_c" | sed '/^$/d' | wc -l)" -eq 4 ] && ok "docs/ 规则改写 4 个:$(echo $docs_c)" || bad "docs/ 规则改写数不符"

if [ -f "$baseline" ]; then
  now=$(cd "$sugg" && find . -type f -print0 | xargs -0 sha256sum | sort)
  b=$(sort < "$baseline" | sha256sum | cut -d' ' -f1); n=$(printf '%s\n' "$now" | sha256sum | cut -d' ' -f1)
  [ "$b" = "$n" ] && ok "建议目录内容未变($(wc -l < "$baseline") 个文件)" || bad "建议目录内容有变化"
  git ls-files --error-unmatch "$sugg" >/dev/null 2>&1 && bad "建议目录被纳入跟踪" || ok "建议目录仍未跟踪"
else
  bad "缺少仓库外基线清单"
fi
echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
