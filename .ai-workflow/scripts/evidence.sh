#!/usr/bin/env bash
# A 档证据留证器:包住一条命令,把「命令 + 完整输出 + 退出码」写成
# rawf-evidence v1 格式文件(格式与完整性定义见 review-standards.md「测试
# 证据档位」与 docs/decisions/0010),落当前任务目录 evidence/。
#
# 用法:evidence.sh <TC-id> [-l <label>] -- <命令> [参数...]
#   目标文件 evidence/<TC-id>[-<label>].log;已存在则拒绝覆盖(.ai/ 只增不改,
#   重跑另起 label)。命令以 argv 形式直接执行,不经 shell;需要管道/重定向
#   时传 -- bash -c '...'。stdin 接 /dev/null(A 档用例非交互)。
# 退出码:透传被包命令的退出码;脚本自身错误(用法、无任务、文件已存在)为 3。
#
# 并发与隔离:无锁、无共享状态、不写任务目录以外的项目路径;唯一的临时对象
# 是 /tmp 下的 FIFO(项目外,不计入评审指纹)。被包命令经 setsid 自成会话。
# 中断(INT/TERM):证据文件建立后即装 trap,任何时刻到达的信号都进入同一套
# 有界清理——尚未启动被包命令则不再启动;已启动则把同一信号转发给整个进程组
# (进程组尚未建立时逐拍重试),5 s 宽限内整组未退出即 KILL;随后照常写尾部。
# 主循环不使用阻塞的 wait,而是每 0.2 s 轮询一次,信号最迟在下一拍被处理。
# 包装器最终退出码固定为 INT=130、TERM=143(不管子进程以什么状态退出,取消
# 操作不会被记成成功)。
# 注意:在无作业控制的 shell 里以 & 后台启动本脚本时,本脚本自身的 INT 按
# POSIX 被忽略且无法 trap,只能用 TERM 中断;前台运行(含终端 Ctrl-C)不受影响。
# 未被中断时不清理子进程组:被包命令须自终止(A 档要求),留下持有输出的
# 后台进程会让本脚本一直等待。
# 不启动 codex,命令行不含 "codex exec",与评审脚本的会话/进程组查杀及
# pgrep 模式无交集。评审进行中不得运行(evidence/ 计入 review.sh 指纹)。
set -uo pipefail

usage() {
  echo "用法:evidence.sh <TC-id> [-l <label>] -- <命令> [参数...]" >&2
  exit 3
}

[ $# -ge 1 ] || usage
tc=$1; shift
label=
if [ "${1:-}" = "-l" ]; then
  [ $# -ge 2 ] || usage
  label=$2; shift 2
fi
[ "${1:-}" = "--" ] || usage
shift
[ $# -ge 1 ] || usage

[[ "$tc" =~ ^TC-[0-9]+[A-Za-z0-9]*$ ]] || { echo "TC 编号不合法:$tc(须匹配 ^TC-[0-9]+[A-Za-z0-9]*$)" >&2; exit 3; }
if [ -n "$label" ]; then
  [[ "$label" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "label 不合法:$label(须匹配 ^[A-Za-z0-9_.-]+$)" >&2; exit 3; }
fi
command -v setsid >/dev/null || { echo "需要 util-linux(setsid)" >&2; exit 3; }

proj="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$proj" ] && [ -d "$proj" ] || { echo "无法定位项目根(CLAUDE_PROJECT_DIR 或 git 仓库)" >&2; exit 3; }
task_rel=$(cat "$proj/.ai/.current-task" 2>/dev/null) || { echo "无进行中任务(.ai/.current-task 不存在)" >&2; exit 3; }
task_dir="$proj/$task_rel"
[ -d "$task_dir" ] || { echo "任务目录不存在:$task_rel" >&2; exit 3; }
ev_dir="$task_dir/evidence"
mkdir -p "$ev_dir"

target="$ev_dir/$tc${label:+-$label}.log"
target_rel="$task_rel/evidence/${target##*/}"
# noclobber 原子创建:同项目内同名并发只有一个胜出
if ! ( set -C; : > "$target" ) 2>/dev/null; then
  echo "证据文件已存在:$target_rel(.ai/ 只增不改;重跑请加 -l <label>)" >&2
  exit 3
fi

# --- 中断处理:证据文件一经建立即生效 ------------------------------------
child=
tee_pid=
fifo=
interrupted=
forwarded=
# try_forward:把收到的信号转发给整个子进程组;组尚未建立(setsid 未完成)时
# kill 失败,不置位,由主循环下一拍重试
try_forward() {
  [ -n "$interrupted" ] && [ -z "$forwarded" ] && [ -n "$child" ] || return 0
  kill -s "$interrupted" -- "-$child" 2>/dev/null && forwarded=1
  return 0
}
# shellcheck disable=SC2329  # 经 trap 字符串调用,静态分析识别不到
on_sig() {
  [ -n "$interrupted" ] && return
  interrupted=$1
  try_forward
}
trap 'on_sig INT' INT
trap 'on_sig TERM' TERM
trap '[ -n "$fifo" ] && rm -f "$fifo"' EXIT

cmd_q=$(printf '%q ' "$@"); cmd_q=${cmd_q% }
git_head=$(git -C "$proj" rev-parse HEAD 2>/dev/null || echo none)
if [ "$git_head" != none ] && [ -n "$(git -C "$proj" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  git_head="$git_head dirty"
fi

{
  echo "# rawf-evidence v1"
  echo "tc: $tc"
  echo "label: $label"
  echo "cmd: $cmd_q"
  echo "cwd: $PWD"
  echo "git_head: $git_head"
  echo "started: $(date -Iseconds)"
  echo "--- output ---"
} >> "$target"
header_len=$(stat -c %s "$target")

rc=0
if [ -z "$interrupted" ]; then
  fifo=$(mktemp -u "${TMPDIR:-/tmp}/rawf-evidence.XXXXXX")
  mkfifo "$fifo" || { echo "无法创建 FIFO" >&2; exit 3; }

  # tee 先于子进程打开 FIFO 读端;子进程及其后代全部退出(写端关闭)后 tee 收到
  # EOF。tee -i 忽略 INT:终端 Ctrl-C 打到整个前台进程组时,tee 须继续收录子
  # 进程的收尾输出,直到写端关闭。
  tee -i -a "$target" < "$fifo" &
  tee_pid=$!
  # 无作业控制时 & 启动的命令按 POSIX 忽略 INT,被包命令将无从响应转发的 INT
  # (如 pytest 的中断收尾)。子 shell 内先 trap - INT 恢复默认处置再 exec;该
  # 子 shell 不是进程组组长,setsid 不分叉,$! 即新会话首进程(= 进程组号)。
  ( trap - INT; exec setsid "$@" < /dev/null > "$fifo" 2>&1 ) &
  child=$!

  # 轮询主循环(不用阻塞的 wait),同时覆盖"等组长退出"与"等 tee 排空"两段:
  # - 未中断:组长退出且 tee 收到 EOF 即结束(被包命令须自终止,见头注释);
  # - 一旦中断——无论信号在启动前、启动中、运行中还是排空阶段到达——逐拍重试
  #   转发;整组与 tee 在 25 拍(5 s)内自行结束即收尾,否则第 25 拍 KILL 整组
  #   与组长,第 30 拍仍未排空(已自行 setsid 脱离进程组的后代持有写端)则
  #   终止 tee。全程有界。
  ticks=0
  while :; do
    leader=0; kill -0 "$child" 2>/dev/null && leader=1
    group=0; kill -0 -- "-$child" 2>/dev/null && group=1
    teeup=0; kill -0 "$tee_pid" 2>/dev/null && teeup=1
    if [ -z "$interrupted" ]; then
      [ "$leader" = 0 ] && [ "$teeup" = 0 ] && break
    else
      try_forward
      [ "$leader" = 0 ] && [ "$group" = 0 ] && [ "$teeup" = 0 ] && break
      if [ "$ticks" -eq 25 ]; then
        kill -KILL -- "-$child" 2>/dev/null
        kill -KILL "$child" 2>/dev/null
      fi
      if [ "$ticks" -ge 30 ]; then
        kill -TERM "$tee_pid" 2>/dev/null
        break
      fi
      ticks=$((ticks + 1))
    fi
    sleep 0.2
  done
  wait "$child" 2>/dev/null; rc=$?
  wait "$tee_pid" 2>/dev/null || true
fi
# 中断的退出码固定,不取子进程状态(子进程捕获信号后正常退出也不算成功;
# 启动前即被中断则被包命令根本未执行,正文为空)
case "$interrupted" in
  INT)  rc=130 ;;
  TERM) rc=143 ;;
esac

size=$(stat -c %s "$target")
bytes=$((size - header_len))
{
  echo
  echo "--- end ---"
  echo "exit: $rc"
  echo "finished: $(date -Iseconds)"
  echo "bytes: $bytes"
} >> "$target"
echo "证据已写入 $target_rel(exit $rc,正文 $bytes 字节)" >&2
exit "$rc"
