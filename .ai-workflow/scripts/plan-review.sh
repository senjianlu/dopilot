#!/usr/bin/env bash
# plan 阶段 Codex 评审:>10 文件改动在实现前先审方案(plan.md)。
# 只读运行 codex(--sandbox read-only),与 review.sh 同构;因 plan 阶段
# 无"评审期间禁改工作区"约束,不设 review.sh 那道完整性哈希双保险。
# 退出码:0=pass 1=fail 3=评审执行异常。
#
# 判定语义以 .ai-workflow/review-standards.md「plan 阶段评审」小节为权威:
# 存在任一 plan-blocker 或 major → fail;仅 minor 或无问题 → pass。
# 轮次上限默认 3;用户明确要求放宽时在 plan.md frontmatter 记
# plan_review_max_rounds(正整数),以该值为准(见 docs/decisions/0003)。
set -euo pipefail

# --- 渲染与原子发布(封装为函数,兼作可控测试点)-------------------------
# render_review <raw_json> <nn>:把结构化输出渲染为与实现层评审同构的 md。
render_review() {
  jq -r --arg nn "$2" '
    def sev_rank: {"plan-blocker": 0, "major": 1, "minor": 2};
    "# Plan 评审:第 \($nn) 轮\n\n## 问题清单",
    (if ((.issues // []) | length) == 0 then "无"
     else ((.issues // []) | sort_by(sev_rank[.severity]) | .[]
       | "- [\(.severity)] \(.id) \(.summary)\n  - 详情:\(.detail)")
     end),
    "\n## 总评\n\(.overall)\n\nVERDICT: \(.verdict)"
  ' "$1"
}

# publish_round <task_dir> <nn> <verdict> <raw_json>:渲染到临时文件后
# mv -n 原子发布。目标已存在(并发发布/占位)则不覆盖并返回 3。
# 注:GNU mv -n 遇已存在目标会静默跳过并返回 0,故须用 [ -e "$tmp" ] 判定
# 是否真的搬走了临时文件(未搬走=发布失败),不能只看 mv 退出码。
publish_round() {
  local td=$1 n=$2 v=$3 raw=$4
  local final="$td/plan-review-round-$n-$v.md"
  local tmp="$td/.plan-review-out-$n.$$"
  if ! render_review "$raw" "$n" > "$tmp"; then
    rm -f "$tmp"; echo "渲染评审文件失败" >&2; return 3
  fi
  if ! mv -n "$tmp" "$final" || [ -e "$tmp" ]; then
    rm -f "$tmp"
    echo "评审结论已被并发发布($final 已存在),本次结果未覆盖" >&2; return 3
  fi
  echo "plan-review-round-$n-$v.md"
}

# resolve_max_rounds <plan.md>:解析轮次上限。只认首个 --- 块(frontmatter)
# 内行首的 plan_review_max_rounds: 字段;字段未出现 → 缺省 3;字段出现但值
# 非正整数(含空值)→ 报错返回 3(该字段仅在用户明确要求放宽时写入,不应
# 出现拼写外的形态)。awk 以 "F=" 前缀标记"字段命中",与"未出现"区分——
# 二者在裸值形态下同为空串,无法直接分辨。
resolve_max_rounds() {
  local hit val
  hit=$(awk '/^---[[:space:]]*$/ { n++; next }
             n == 1 && /^plan_review_max_rounds:/ {
               sub(/^plan_review_max_rounds:/, "")
               gsub(/^[[:space:]]+|[[:space:]]+$/, "")
               print "F=" $0; exit }
             n >= 2 { exit }' "$1")
  if [ -z "$hit" ]; then
    echo 3
    return 0
  fi
  val=${hit#F=}
  if [[ "$val" =~ ^[1-9][0-9]*$ ]]; then
    echo "$val"
  else
    echo "plan.md 的 plan_review_max_rounds 非法(须为正整数,实际为:${val:-空})" >&2
    return 3
  fi
}

# 测试可控入口:直接调用发布函数(绕过轮次计数),验证 mv -n 不覆盖行为;
# __resolve_max_rounds 同理,验证上限解析的缺省/合法/非法分支。
if [ "${1:-}" = "__publish_round" ]; then
  shift
  publish_round "$@"
  exit $?
fi
if [ "${1:-}" = "__resolve_max_rounds" ]; then
  shift
  resolve_max_rounds "$@"
  exit $?
fi

# --- 主流程(扁平于顶层:lock 等为全局变量,EXIT trap 可见)---------------
command -v codex >/dev/null || { echo "codex CLI 未安装或不在 PATH" >&2; exit 3; }

proj="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$proj"

task_rel=$(cat .ai/.current-task 2>/dev/null) \
  || { echo "无进行中任务(.ai/.current-task 不存在)" >&2; exit 3; }
task_dir="$proj/$task_rel"
[ -d "$task_dir" ] || { echo "任务目录不存在:$task_rel" >&2; exit 3; }
plan="$task_dir/plan.md"
[ -f "$plan" ] || { echo "plan.md 不存在,先完成 /rawf-plan 起草" >&2; exit 3; }

# 原子锁:mkdir 原子性使"检查-评审-发布"全程互斥,并发第二实例直接拒绝
lock="$task_dir/.plan-review-lock"
if ! mkdir "$lock" 2>/dev/null; then
  echo "已有 plan 评审在进行中($task_rel/.plan-review-lock 存在);确认无并发后删除该目录重跑" >&2
  exit 3
fi
trap 'rm -rf "$lock"' EXIT

# 轮次:count=已有 plan-review-round-*.md 数量;nn=count+1。
# 机器上限:缺省 3,可被 plan.md frontmatter 的用户授权值放宽;
# count>=上限直接拒绝,交人工。
max_rounds=$(resolve_max_rounds "$plan") || exit 3
shopt -s nullglob
rounds=("$task_dir"/plan-review-round-*.md)
shopt -u nullglob
count=${#rounds[@]}
if [ "$count" -ge "$max_rounds" ]; then
  echo "plan 评审已达 $max_rounds 轮上限,仍未收敛;停止自动评审,交人工判断" >&2
  exit 3
fi
nn=$(printf '%02d' "$((count + 1))")

prompt=$(cat .ai-workflow/prompts/plan-review.md)
prompt="${prompt//\{\{TASK_DIR\}\}/$task_rel}"
prompt="${prompt//\{\{ROUND\}\}/$nn}"

# 原始输出直接落在任务目录(已由 .gitignore 忽略),非法/异常时保留供排查。
raw="$task_dir/.plan-review-raw-$nn.json"
rm -f "$raw"

codex_rc=0
codex exec --sandbox read-only -C "$proj" \
  --output-schema "$proj/.ai-workflow/schemas/plan-review.schema.json" \
  --output-last-message "$raw" "$prompt" || codex_rc=$?

if [ "$codex_rc" -ne 0 ]; then
  echo "codex exec 执行失败(退出码 $codex_rc),评审未完成;检查 codex login/额度/网络后重跑" >&2
  exit 3
fi
[ -f "$raw" ] || { echo "codex 退出 0 但未产出评审输出文件,评审未完成;请重跑评审" >&2; exit 3; }

# 结构化解析 + 交叉校验:JSON 合法性 → verdict → 按严重度清单推导并比对。
if ! jq -e . "$raw" >/dev/null 2>&1; then
  echo "评审输出不是合法 JSON,原始输出保留在 $task_rel/.plan-review-raw-$nn.json" >&2
  exit 3
fi
verdict=$(jq -r '.verdict // empty' "$raw")
case "$verdict" in
  pass|fail) ;;
  *)
    echo "评审输出缺少合法 verdict 字段,原始输出保留在 $task_rel/.plan-review-raw-$nn.json" >&2
    exit 3 ;;
esac
blocking=$(jq '[.issues // [] | .[] | select(.severity == "plan-blocker" or .severity == "major")] | length' "$raw")
if [ "$blocking" -gt 0 ]; then derived=fail; else derived=pass; fi
if [ "$verdict" != "$derived" ]; then
  echo "评审自报结论($verdict)与严重度清单推导($derived)矛盾,按判定规则该评审无效,原始输出保留在 $task_rel/.plan-review-raw-$nn.json" >&2
  exit 3
fi

out=$(publish_round "$task_dir" "$nn" "$verdict" "$raw") || exit 3
echo "$out"
[ "$verdict" = "pass" ]
