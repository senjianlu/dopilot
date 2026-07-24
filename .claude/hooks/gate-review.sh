#!/usr/bin/env bash
# Stop hook:最新一轮实现尚未评审时,不许结束回合(只拦一次)。
# 放行 = 无输出退出 0;拦截 = stdout 输出 decision: block 的 JSON 并退出 0。
set -euo pipefail

block() {
  jq -n --arg r "$1" '{decision: "block", reason: $r}'
  exit 0
}

input=$(cat)
[ "$(echo "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

proj="${CLAUDE_PROJECT_DIR:-$(pwd)}"
task_rel=$(cat "$proj/.ai/.current-task" 2>/dev/null) || exit 0
task_dir="$proj/$task_rel"
[ -d "$task_dir" ] || exit 0

# nullglob 数组计数:无匹配时为 0,不像 ls 管道在 set -e/pipefail 下
# 会以非零退出码使 hook 崩溃(旧实现靠"exit 1 被视为非阻塞错误"侥幸放行);
# 评审文件存在性判断同用数组,避免 nullglob 下空 glob 令 ls 误列当前目录
shopt -s nullglob
rounds=("$task_dir"/implementation-round-*.md)
count=${#rounds[@]}
[ "$count" -gt 0 ] || exit 0
nn=$(printf '%02d' "$count")
reviews=("$task_dir"/review-round-"$nn"-*.md)
shopt -u nullglob

if [ "${#reviews[@]}" -eq 0 ]; then
  block "rawf 工作流拦截:第 $nn 轮实现尚未经过 Codex 评审。请立即运行 /rawf-review;若因故必须先征询用户,说明原因后可再次结束。"
fi
exit 0
