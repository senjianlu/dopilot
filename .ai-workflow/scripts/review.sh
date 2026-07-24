#!/usr/bin/env bash
# 调用 Codex 评审当前改动。退出码:0=pass 1=fail 3=评审执行异常
# 评审以只读沙箱(--sandbox read-only)直审原仓库,不建副本(与
# plan-review.sh 同构;取消副本的决策见 docs/decisions/0005)。评审者不
# 运行任何测试,测试核验走证据协议(review-standards.md「评审动作边界」)。
# 完整性哈希保留为双保险:检测评审期间主工作区的并发写入,兜底沙箱失效;
# 只读沙箱生效且无并发写入时理应永不触发。
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
# TEMPLATE: 按项目构建产物增删排除项。
hash_excludes=(
  --exclude='.review-raw-*'
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

# --- 主流程 ---------------------------------------------------------------
command -v codex >/dev/null || { echo "codex CLI 未安装或不在 PATH" >&2; exit 3; }

proj="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$proj"

task_rel=$(cat .ai/.current-task 2>/dev/null) || { echo "无进行中任务(.ai/.current-task 不存在)" >&2; exit 3; }
task_dir="$proj/$task_rel"
[ -d "$task_dir" ] || { echo "任务目录不存在:$task_rel" >&2; exit 3; }

# 同轮唯一性由原子锁保证:mkdir 原子性使"检查-评审-发布"全程互斥,
# 并发第二实例直接拒绝;锁为临时空目录,对 git 与完整性哈希均不可见
lock="$task_dir/.review-lock"
if ! mkdir "$lock" 2>/dev/null; then
  echo "已有评审在进行中($task_rel/.review-lock 存在);确认无并发评审后删除该目录重跑" >&2
  exit 3
fi
trap 'rm -rf "$lock"' EXIT

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

prompt=$(cat .ai-workflow/prompts/review.md)
prompt="${prompt//\{\{TASK_DIR\}\}/$task_rel}"
prompt="${prompt//\{\{ROUND\}\}/$nn}"

pre_hash=$(workspace_hash)

# 原始输出直接落任务目录(已由 .gitignore 忽略、hash_excludes 排除),
# 由 codex CLI 进程自身写入,不经受沙箱约束(沙箱只管模型生成的 shell
# 命令);非法/异常时原地保留供排查,无需任何回搬逻辑。
raw_name=".review-raw-$nn.json"
raw="$task_dir/$raw_name"
rm -f "$raw"   # 清除历史遗留输出,防陈旧结论被误用

codex_rc=0
codex exec --sandbox read-only -C "$proj" \
  --output-schema "$proj/.ai-workflow/schemas/review.schema.json" \
  --output-last-message "$raw" "$prompt" || codex_rc=$?

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

# 渲染为与历史轮次同构的 markdown(问题按严重度排序,plan-blocker 置顶);
# --arg render 1 为渲染调用的特征标记,便于测试注入,对 jq 语义无影响
render_review() {
  jq -r --arg render 1 --arg nn "$nn" '
    def sev_rank: {"plan-blocker": 0, "blocker": 1, "major": 2, "minor": 3};
    "# 评审:第 \($nn) 轮\n\n## 问题清单",
    (if ((.issues // []) | length) == 0 then "无"
     else ((.issues // []) | sort_by(sev_rank[.severity]) | .[]
       | "- [\(.severity)] \(.id) \(.summary)\n  - 详情:\(.detail)")
     end),
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
