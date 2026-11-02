#!/usr/bin/env bash
# 调用 Codex 评审当前改动。退出码:0=pass 1=fail 3=评审执行异常(含看门狗终止)
# 评审以只读沙箱(--sandbox read-only)直审原仓库,不建副本(与
# plan-review.sh 同构;取消副本的决策见 docs/decisions/0005)。评审者不
# 运行任何测试,测试核验走证据协议(review-standards.md「评审动作边界」)。
# 完整性哈希保留为双保险:检测评审期间主工作区的并发写入,兜底沙箱失效;
# 只读沙箱生效且无并发写入时理应永不触发。
#
# 卡死治理(docs/decisions/0009):codex 的 stdin 接 /dev/null(codex 在 stdin
# 非终端时必读到 EOF);--json 事件流落盘作进度信号,静默超过
# RAWF_REVIEW_IDLE_SECONDS 或总时长超过 RAWF_REVIEW_MAX_SECONDS 即按会话 +
# 进程组终止 codex 并 exit 3;锁为 flock 文件,随持有进程退出自动释放。
# 运行环境要求 Linux:util-linux(flock、setsid)与 procps(pgrep)。
set -euo pipefail

# --- 完整性指纹(封装于顶层,兼作可控测试点)-----------------------------
# 快照口径:已跟踪改动 + 未跟踪文件逐条 NUL 定界记账
# (类型\0路径\0载荷\0;符号链接记链接目标,普通文件记可执行位+内容哈希),
# diff 段与未跟踪段各自先哈希再合并,无分隔符歧义与跨段拼接歧义。
# 未跟踪文件不按 .gitignore 排除(防 .env 等被忽略文件遭篡改而不被发现),
# 只排除明确允许的评审/测试产物。
# .claude/ 例外排除:评审强制后台运行,主会话在评审期间仍活跃,而 Claude
# Code 会自动写 .claude/settings.local.json(记录权限授予,不经工具、无从拦截),
# 若纳入指纹会把这类并发写入误判为"隔离失败"致评审无效。故整目录不计入。
# .review-lock:flock 锁文件常驻任务目录(永不删除),评审前后都在,排除只为
# 让 git status 在评审期间保持干净。
# TEMPLATE: 按项目构建产物增删排除项。
hash_excludes=(
  --exclude='.review-raw-*'
  --exclude='.review-lock'
  --exclude='.claude/'
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.pytest_cache/'
  --exclude='.venv/' --exclude='node_modules/' --exclude='dist/' --exclude='.next/'
  --exclude='.DS_Store'
)
workspace_hash() {
  {
    git diff HEAD -- . ':(exclude).claude' | shasum
    git ls-files --others -z "${hash_excludes[@]}" \
      | while IFS= read -r -d '' f; do
          if [ -L "$f" ]; then
            printf 'symlink\0%s\0' "$f"
            readlink "$f"
            printf '\0'
          else
            if [ -x "$f" ]; then m=x; else m=-; fi
            printf 'file\0%s\0%s\0' "$f" "$m"
            shasum < "$f"
            printf '\0'
          fi
        done | shasum
  } | shasum | cut -d' ' -f1
}

# 测试可控入口:脱离 codex 与主流程单测指纹敏感性(CLAUDE_PROJECT_DIR
# 指向测试用临时工作区),循 plan-review.sh __publish_round 先例。
if [ "${1:-}" = "__workspace_hash" ]; then
  proj="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
  cd "$proj"
  workspace_hash
  exit $?
fi

# --- 受管进程集合与终止 ---------------------------------------------------
# codex 经 setsid 启动,成为新会话与新进程组首进程;受管集合 = 同会话 ∪
# 同进程组 ∪ 自身。中间进程退出、后代改挂 init 后 sid/pgid 不变,仍能命中。
managed_pids() {
  { pgrep -s "$1" || true; pgrep -g "$1" || true; echo "$1"; } 2>/dev/null \
    | sort -un | while read -r p; do kill -0 "$p" 2>/dev/null && echo "$p" || true; done
}
# kill_codex_tree <sid>:TERM 整组 + 逐 pid,等至多 10 s;仍存活则 KILL 升级
# (按当时重新取得的集合),再等 3 s;残留只告警不阻断退出。
kill_codex_tree() {
  local sid=$1 p alive
  kill -TERM -- "-$sid" 2>/dev/null || true
  for p in $(managed_pids "$sid"); do kill -TERM "$p" 2>/dev/null || true; done
  for _ in $(seq 1 20); do
    alive=$(managed_pids "$sid"); [ -z "$alive" ] && return 0; sleep 0.5
  done
  kill -KILL -- "-$sid" 2>/dev/null || true
  for p in $(managed_pids "$sid"); do kill -KILL "$p" 2>/dev/null || true; done
  for _ in $(seq 1 6); do
    alive=$(managed_pids "$sid"); [ -z "$alive" ] && return 0; sleep 0.5
  done
  echo "警告:以下受管进程仍存活:$(echo "$alive" | tr '\n' ' ')" >&2
}

# lock_holders:只列真正持有 flock 的进程(pid 命令名)。判据是
# /proc/<pid>/fdinfo/<fd> 的 lock: 行(FLOCK + 锁文件 inode)——被继承的 fd
# 同样带该行,仅打开未持锁的 fd 没有;/proc/locks 里的 pid 是已退出的 flock
# 命令进程,不可用。调用前须先关闭本实例自己的锁 fd。
lock_holders() {
  local real ino fd pid
  real=$(realpath "$lock" 2>/dev/null) || return 0
  ino=$(stat -c %i "$lock" 2>/dev/null) || return 0
  # find -lname 单进程完成全量匹配(逐 fd readlink 要 fork 数千次,快照会过期)
  # find 对无权限的 /proc 条目会返回非零,须吞掉,否则 set -e/pipefail 下整个
  # 命令替换失败、脚本静默退出
  { find /proc/[0-9]*/fd -maxdepth 1 -lname "$real" 2>/dev/null || true; } | while read -r fd; do
    pid=${fd#/proc/}; pid=${pid%%/*}
    [ "$pid" = "$$" ] && continue
    grep -qE "^lock:.*FLOCK.*:${ino}[[:space:]]" "/proc/$pid/fdinfo/${fd##*/}" 2>/dev/null || continue
    echo "$pid $(cat "/proc/$pid/comm" 2>/dev/null)"
  done | sort -un
}

positive_int() {
  [[ "$2" =~ ^[1-9][0-9]*$ ]] && return 0
  echo "$1 须为正整数,实际为:${2:-空}" >&2
  return 1
}

# --- 主流程 ---------------------------------------------------------------
for tool in flock setsid pgrep; do
  command -v "$tool" >/dev/null \
    || { echo "需要 util-linux(flock、setsid)与 procps(pgrep):缺少 $tool" >&2; exit 3; }
done
command -v codex >/dev/null || { echo "codex CLI 未安装或不在 PATH" >&2; exit 3; }

idle_limit=${RAWF_REVIEW_IDLE_SECONDS:-900}
max_limit=${RAWF_REVIEW_MAX_SECONDS:-3600}
poll=${RAWF_REVIEW_POLL_SECONDS:-5}
positive_int RAWF_REVIEW_IDLE_SECONDS "$idle_limit" || exit 3
positive_int RAWF_REVIEW_MAX_SECONDS "$max_limit" || exit 3
positive_int RAWF_REVIEW_POLL_SECONDS "$poll" || exit 3

proj="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$proj"

task_rel=$(cat .ai/.current-task 2>/dev/null) || { echo "无进行中任务(.ai/.current-task 不存在)" >&2; exit 3; }
task_dir="$proj/$task_rel"
[ -d "$task_dir" ] || { echo "任务目录不存在:$task_rel" >&2; exit 3; }

# 同轮唯一性由 flock 保证:fd 9 在脚本整个生命周期持有,"检查-评审-发布"
# 全程互斥;持有进程(含继承 fd 的 codex)全部退出即自动释放,没有残留态。
# 锁文件常驻、永不删除(删除-重建会让两个打开者持有不同 inode 的锁)。
lock="$task_dir/.review-lock"
if [ -d "$lock" ]; then
  echo "检测到旧版锁目录 $task_rel/.review-lock(升级前残留);确认 pgrep -f 'codex exec' 无旧评审进程后执行 rmdir 该目录再重跑" >&2
  exit 3
fi
if ! { true 9>>"$lock"; } 2>/dev/null; then
  echo "无法打开锁文件 $task_rel/.review-lock" >&2; exit 3
fi
exec 9>>"$lock"
flock_rc=0
flock -n -E 75 9 || flock_rc=$?
case "$flock_rc" in
  0) ;;
  75)
    exec 9>&-
    recorded=$(sed -n 's/^script=//p' "$lock" | head -1)
    holders=$(lock_holders)
    # 持有者里是否还有评审脚本进程(按 cmdline 判断,不依赖锁文件元数据):
    # 有 → 正常并发;无 → 脚本被强杀后遗留的评审进程
    script_alive=0
    for hp in $(echo "$holders" | awk '{print $1}'); do
      if { tr '\0' ' ' < "/proc/$hp/cmdline"; } 2>/dev/null | grep -q 'review.sh'; then script_alive=1; fi
    done
    # 快照可能过期(扫描期间评审刚结束):输出前复核锁仍被持有、名单仍存活
    recheck=0
    flock -n -E 75 "$lock" true 2>/dev/null || recheck=$?
    if [ "$recheck" -eq 0 ]; then
      echo "评审刚结束,锁 $task_rel/.review-lock 已释放;请重跑" >&2
      exit 3
    fi
    alive=$(echo "$holders" | while read -r hp hc; do
      [ -n "$hp" ] && kill -0 "$hp" 2>/dev/null && echo "$hp $hc" || true; done)
    {
      echo "已有评审在进行中,锁 $task_rel/.review-lock 被以下进程持有:"
      echo "${alive:-(未定位到持有进程,可能刚结束;请重跑)}"
      if [ -n "$alive" ] && [ "$script_alive" = 0 ]; then
        echo "持有者中已无评审脚本进程(记录的脚本 pid ${recorded:-未知}),上述为脚本被强杀后遗留的评审进程;确认后执行 kill -TERM $(echo "$alive" | awk '{print $1}' | tr '\n' ' ')再重跑"
      elif [ -n "$alive" ]; then
        echo "待其结束后重跑"
      fi
    } >&2
    exit 3 ;;
  *) echo "锁探测失败(flock 退出码 $flock_rc)" >&2; exit 3 ;;
esac
printf 'script=%s\n' "$$" > "$lock"

codex_pid=
cleanup() { [ -n "$codex_pid" ] && kill_codex_tree "$codex_pid"; return 0; }
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# nullglob 数组计数:无匹配为 0,避免 ls 管道在 set -e/pipefail 下以
# 非预期退出码崩溃(会与"评审结论 fail"的退出码 1 冲突)
shopt -s nullglob
rounds=("$task_dir"/implementation-round-*.md)
shopt -u nullglob   # 立即关闭:后续 review-round 存在性 glob 依赖非空语义
count=${#rounds[@]}
[ "$count" -gt 0 ] || { echo "尚无实现记录,先完成 /rawf-implement" >&2; exit 3; }
nn=$(printf '%02d' "$count")

# 同一轮只评一次:.ai/ 历史只增不改
if ls "$task_dir"/review-round-"$nn"-*.md >/dev/null 2>&1; then
  echo "第 $nn 轮已有评审文件,按'历史只增不改'拒绝重评;确需重评请用户手动处置旧文件后重跑" >&2
  exit 3
fi

# A 档证据机器核验(docs/decisions/0010):结构不完整的证据不送评审——
# 格式问题由脚本判定并直接开出补交清单,不消耗 codex 评审轮次;通过的报告
# 注入 prompt,评审者只核内容不核格式。plan 未声明 evidence_format(历史
# 任务)→ 跳过,占位改为提示评审者自行核对格式。
# stdout(报告表)与 stderr(补交清单 / 错误诊断)按产生顺序合并捕获:
# 通过时 stderr 为空,注入 prompt 的就是纯报告;失败时整段原样转 stderr
ev_rc=0
ev_report=$(bash "$proj/.ai-workflow/scripts/evidence-check.sh" "$nn" 2>&1) || ev_rc=$?
case "$ev_rc" in
  0) ;;
  1)
    { echo "证据核验未通过(evidence-check),评审未启动;按补交清单补齐证据或修正实现记录后重跑 review.sh(当前轮尚未评审,不开新轮):"; echo "$ev_report"; } >&2
    exit 3 ;;
  2) ev_report="(历史任务:plan 未声明 evidence_format: v1,未经机器核验;A 档证据的格式——命令、完整输出、退出码——由评审按 review-standards.md 自行核对)" ;;
  *) echo "evidence-check 执行异常(退出码 $ev_rc):$ev_report" >&2; exit 3 ;;
esac

# bash 5.2 起 patsub_replacement 默认开启:替换文本里的 & 会被换成匹配原文、\& 丢
# 反斜杠,证据报告(B/C 档证据格原文、%q 转义的 cmd)会被改写。关闭后再做占位
# 替换(与 plan-review.sh 同一处理,见 docs/decisions/0012)。
shopt -u patsub_replacement 2>/dev/null || true
prompt=$(cat .ai-workflow/prompts/review.md)
prompt="${prompt//\{\{TASK_DIR\}\}/$task_rel}"
prompt="${prompt//\{\{ROUND\}\}/$nn}"
prompt="${prompt//\{\{EVIDENCE_REPORT\}\}/$ev_report}"

pre_hash=$(workspace_hash)

# 原始输出直接落任务目录(已由 .gitignore 忽略、hash_excludes 排除),
# 由 codex CLI 进程自身写入,不经受沙箱约束(沙箱只管模型生成的 shell
# 命令);非法/异常时原地保留供排查,无需任何回搬逻辑。
# 事件流(--json)同样落任务目录,文件名命中 .review-raw-* 模式。
raw_name=".review-raw-$nn.json"
raw="$task_dir/$raw_name"
events="$task_dir/.review-raw-$nn.events.jsonl"
rm -f "$raw" "$events"   # 清除历史遗留输出,防陈旧结论被误用

setsid codex exec --json --sandbox read-only -C "$proj" \
  --output-schema "$proj/.ai-workflow/schemas/review.schema.json" \
  --output-last-message "$raw" "$prompt" </dev/null >"$events" &
codex_pid=$!
# 子进程要先执行到 setsid(2) 才成为会话首进程,最多等 2 s;已退出(极快完成)
# 则无需受管,直接放过。
sid_ok=0
for _ in $(seq 1 20); do
  if ! kill -0 "$codex_pid" 2>/dev/null; then sid_ok=1; break; fi
  if [ "$(ps -o sid= -p "$codex_pid" 2>/dev/null | tr -d ' ')" = "$codex_pid" ]; then sid_ok=1; break; fi
  sleep 0.1
done
if [ "$sid_ok" != 1 ]; then
  echo "setsid 未按预期生效(codex pid $codex_pid 不是会话首进程),无法受管终止" >&2
  exit 3
fi

# 看门狗:以事件文件字节数为进度信号;醒来先查存活,已结束则不做超时判定
start=$SECONDS; last_size=0; last_change=$SECONDS; reason=
while kill -0 "$codex_pid" 2>/dev/null; do
  sleep "$poll" 9>&-   # 不让 sleep 继承锁 fd:脚本被强杀时它不应再持锁
  kill -0 "$codex_pid" 2>/dev/null || break
  size=$(wc -c < "$events" 2>/dev/null || echo 0)
  if [ "$size" != "$last_size" ]; then last_size=$size; last_change=$SECONDS; fi
  if [ $((SECONDS - last_change)) -ge "$idle_limit" ]; then reason=idle; break; fi
  if [ $((SECONDS - start)) -ge "$max_limit" ]; then reason=max; break; fi
done

codex_rc=0
if [ -n "$reason" ]; then
  kill_codex_tree "$codex_pid"
  wait "$codex_pid" 2>/dev/null || true
  codex_pid=
  case "$reason" in
    idle) echo "评审 ${idle_limit} 秒无新事件,判定卡死,已终止;请重跑评审" >&2 ;;
    max)  echo "评审超过墙钟上限 ${max_limit} 秒,已终止;请重跑评审" >&2 ;;
  esac
  exit 3
fi
wait "$codex_pid" || codex_rc=$?
# codex 主进程已退出但受管后代仍存活(继承锁 fd 会一直持锁)→ 一并清理
if [ -n "$(managed_pids "$codex_pid")" ]; then
  echo "警告:codex 已退出但受管后代仍存活,清理中" >&2
  kill_codex_tree "$codex_pid"
fi
codex_pid=

# 双保险:主工作区必须分毫未动(只读沙箱生效且无并发写入时恒真)
post_hash=$(workspace_hash)
if [ "$pre_hash" != "$post_hash" ]; then
  echo "主工作区在评审期间发生改动(沙箱未能阻止,或存在并发写入),本次评审无效。请 git status 检查后重跑。" >&2
  exit 3
fi

if [ "$codex_rc" -ne 0 ]; then
  echo "codex exec 执行失败(退出码 $codex_rc),评审未完成;检查 codex login/额度/网络后重跑" >&2
  exit 3
fi

if [ ! -f "$raw" ]; then
  echo "codex 退出 0 但未产出评审输出文件,评审未完成;请重跑评审" >&2
  exit 3
fi

# 结构化解析:JSON 合法性 → 字段提取 → 按判定规则推导并交叉校验。
# 判定规则(review-standards.md)是严重度清单的纯函数,脚本推导后与评审者
# 自报 verdict 比对,矛盾的评审直接判无效,不被采纳。
if ! jq -e . "$raw" >/dev/null 2>&1; then
  echo "评审输出不是合法 JSON,原始输出保留在 $task_rel/$raw_name" >&2
  exit 3
fi
verdict=$(jq -r '.verdict // empty' "$raw")
case "$verdict" in
  pass|fail) ;;
  *)
    echo "评审输出缺少合法 verdict 字段,原始输出保留在 $task_rel/$raw_name" >&2
    exit 3 ;;
esac
blocking=$(jq '[.issues // [] | .[] | select(.severity == "blocker" or .severity == "major")] | length' "$raw")
if [ "$blocking" -gt 0 ]; then derived=fail; else derived=pass; fi
if [ "$verdict" != "$derived" ]; then
  echo "评审自报结论($verdict)与严重度清单推导($derived)矛盾,按判定规则该评审无效,原始输出保留在 $task_rel/$raw_name" >&2
  exit 3
fi

# 渲染为与历史轮次同构的 markdown(问题按严重度排序,plan-blocker 置顶;
# 范围核对单列一节,不计入 pass/fail,缺字段按空数组容错);
# --arg render 1 为渲染调用的特征标记,便于测试注入,对 jq 语义无影响
render_review() {
  jq -r --arg render 1 --arg nn "$nn" '
    def sev_rank: {"plan-blocker": 0, "blocker": 1, "major": 2, "minor": 3};
    "# 评审:第 \($nn) 轮\n\n## 问题清单",
    (if ((.issues // []) | length) == 0 then "无"
     else ((.issues // []) | sort_by(sev_rank[.severity]) | .[]
       | "- [\(.severity)] \(.id) \(.summary)\n  - 详情:\(.detail)")
     end),
    "\n## 范围核对",
    (if ((.scope_findings // []) | length) == 0 then "无"
     else ((.scope_findings // []) | .[] | "- \(.)") end),
    "\n## 总评\n\(.overall)\n\nVERDICT: \(.verdict)"
  ' "$raw"
}

# 原子发布:先在同目录(同文件系统)写全临时文件,mv -n 原子改名发布;
# 渲染中途失败只污染临时文件(随即清理),不会留下半成品结论、不阻断重试。
final="$task_dir/review-round-$nn-$verdict.md"
tmp_out="$task_dir/.review-out-$nn.$$"
if ! render_review > "$tmp_out"; then
  rm -f "$tmp_out"
  echo "渲染评审文件失败" >&2
  exit 3
fi
if ! mv -n "$tmp_out" "$final" || [ -e "$tmp_out" ]; then
  rm -f "$tmp_out"
  echo "评审结论已被并发发布($final 已存在),本次结果未覆盖" >&2
  exit 3
fi
echo "review-round-$nn-$verdict.md"
[ "$verdict" = "pass" ]
