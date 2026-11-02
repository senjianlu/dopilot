#!/usr/bin/env bash
# A 档证据机器核验:以 plan.md 测试用例表为基准,逐条核对实现记录
# implementation-round-<NN>.md 的测试结果表及其引用的 rawf-evidence v1 文件
# 的结构完整性(规则见 review-standards.md「测试证据档位」与 docs/decisions/0010)。
# 只读,不改任何文件。review.sh 在评审启动前调用;实现者写完记录后也应自跑。
#
# 用法:evidence-check.sh [NN]   (缺省 = 最新实现轮)
# 退出码:0 = 全部通过;1 = 存在不通过项(报告表在 stdout,补交清单在 stderr);
#        2 = plan 未声明 evidence_format: v1(历史任务,跳过机器核验);
#        3 = 脚本自身错误(无任务、无实现记录等)。
# 判定标记:
#   OK            A 档证据文件结构完整
#   NO-REF        A 档行的证据单元格未引用任何 *.log 文件
#   MISSING       引用的证据文件不存在
#   NO-HEADER     首行不是 "# rawf-evidence v1"
#   BAD-HEADER    头部缺 tc:/cmd:/cwd:/git_head:/started: 之一(或为空)
#   NO-BODY       缺 "--- output ---" 行
#   NO-FOOTER     最后一个 "--- end ---" 之后缺 exit:/finished:/bytes:
#   BAD-EXIT      exit: 不是 0..255 整数
#   TRUNCATED     正文区字节数 ≠ bytes:
#   BLOCKED       结果为 blocked(不得进评审)
#   MISSING-ROW   plan 有此用例、记录无
#   TIER-MISMATCH 记录档位 ≠ plan 档位
#   EXTRA-ROW     记录有、plan 无(只列出,不影响退出码)
#   EMPTY-TABLE   plan 用例表或记录测试结果表缺失/为空
#   评审核验      B / C 档,由评审按档位核验
set -uo pipefail
export LC_ALL=C

proj="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$proj" ] && [ -d "$proj" ] || { echo "无法定位项目根" >&2; exit 3; }
task_rel=$(cat "$proj/.ai/.current-task" 2>/dev/null) || { echo "无进行中任务(.ai/.current-task 不存在)" >&2; exit 3; }
task_dir="$proj/$task_rel"
[ -d "$task_dir" ] || { echo "任务目录不存在:$task_rel" >&2; exit 3; }
plan="$task_dir/plan.md"
[ -f "$plan" ] || { echo "plan.md 不存在:$task_rel/plan.md" >&2; exit 3; }

if [ -n "${1:-}" ]; then
  nn=$(printf '%02d' "$((10#$1))") 2>/dev/null || { echo "轮次须为数字" >&2; exit 3; }
else
  shopt -s nullglob
  rounds=("$task_dir"/implementation-round-*.md)
  shopt -u nullglob
  [ "${#rounds[@]}" -gt 0 ] || { echo "尚无实现记录" >&2; exit 3; }
  nn=$(printf '%02d' "${#rounds[@]}")
fi
record="$task_dir/implementation-round-$nn.md"
[ -f "$record" ] || { echo "实现记录不存在:$task_rel/implementation-round-$nn.md" >&2; exit 3; }

# 只认首个 --- 块内的 evidence_format: v1
fmt=$(awk '/^---[[:space:]]*$/ { n++; next } n == 1 && /^evidence_format:/ { sub(/^evidence_format:[[:space:]]*/, ""); sub(/[[:space:]]+$/, ""); print; exit }' "$plan")
if [ "$fmt" != "v1" ]; then
  echo "plan 未声明 evidence_format: v1(历史任务),跳过机器核验;A 档格式由评审自行核对"
  exit 2
fi

# table_rows <file> <section-heading-regex>:输出该节内的表格数据行,
# 各列以 \t 分隔、去首尾空白,跳过表头(首列为"编号")与分隔行(|---)。
table_rows() {
  awk -v sec="$2" '
    /^## / { insec = ($0 ~ sec) ? 1 : 0; next }
    insec && /^\|/ {
      line = $0
      sub(/^\|/, "", line); sub(/\|[[:space:]]*$/, "", line)
      n = split(line, c, "|")
      out = ""
      for (i = 1; i <= n; i++) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", c[i])
        out = out (i > 1 ? "\t" : "") c[i]
      }
      if (c[1] ~ /^-+$/ || c[1] == "编号" || c[1] == "") next
      print out
    }' "$1"
}

# 基准:plan 用例表(编号 → 档位)
declare -A plan_tier
plan_ids=()
while IFS=$'\t' read -r id tier _; do
  [[ "$id" =~ ^TC- ]] || continue
  plan_tier["$id"]=$tier
  plan_ids+=("$id")
done < <(table_rows "$plan" '^## 测试用例')

# 记录:测试结果表(编号、档位、结果、证据)
declare -A rec_tier rec_result rec_evidence
rec_ids=()
while IFS=$'\t' read -r id tier result evidence _; do
  [[ "$id" =~ ^TC- ]] || continue
  rec_tier["$id"]=$tier; rec_result["$id"]=${result:-}; rec_evidence["$id"]=${evidence:-}
  rec_ids+=("$id")
done < <(table_rows "$record" '^## 测试结果')

fail=0
rows=()      # 渲染行
todo=()      # 补交清单

add_row() { rows+=("| $1 | $2 | $3 | $4 | $5 | $6 | $7 |"); }
need() { fail=1; todo+=("$1"); }

# check_file <path> → 输出 "<标记>\x1f<exit>\x1f<cmd 摘要>"(\x1f 分隔:tab 属 IFS 空白,空字段会被折叠)
check_file() {
  local f=$1
  [ -f "$f" ] || { printf 'MISSING\x1f\x1f\n'; return; }
  [ "$(head -n 1 "$f")" = "# rawf-evidence v1" ] || { printf 'NO-HEADER\x1f\x1f\n'; return; }
  # 头部 = 首个 --- output --- 之前
  local hdr; hdr=$(awk '/^--- output ---$/ { exit } { print }' "$f")
  local missing=() k v
  for k in tc cmd cwd git_head started; do
    v=$(printf '%s\n' "$hdr" | awk -v k="$k" 'index($0, k ": ") == 1 { sub("^" k ": ", ""); print; exit }')
    [ -n "$v" ] || missing+=("$k")
  done
  local cmd; cmd=$(printf '%s\n' "$hdr" | awk 'index($0, "cmd: ") == 1 { sub(/^cmd: /, ""); print; exit }')
  local cmd_short=${cmd:0:60}; [ "${#cmd}" -gt 60 ] && cmd_short="$cmd_short…"
  cmd_short=${cmd_short//|/\\|}
  if [ "${#missing[@]}" -gt 0 ]; then printf 'BAD-HEADER(缺 %s)\x1f\x1f%s\n' "$(IFS=,; echo "${missing[*]}")" "$cmd_short"; return; fi
  # 字节级定位:正文区起点 = 首个 output 行之后;终点 = 最后一个 end 行之前的换行
  local pos; pos=$(awk '
    { off = cum; cum += length($0) + 1
      if (!o && $0 == "--- output ---") { o = 1; start = cum }
      if ($0 == "--- end ---") { e = 1; endoff = off }
    }
    END { if (!o) print "NO-BODY"; else if (!e) print "NO-FOOTER"; else print start, endoff }' "$f")
  case "$pos" in
    NO-BODY|NO-FOOTER) printf '%s\x1f\x1f%s\n' "$pos" "$cmd_short"; return ;;
  esac
  local start endoff; read -r start endoff <<< "$pos"
  local footer; footer=$(tail -c +"$((endoff + 1))" "$f")
  local ex fin by
  ex=$(printf '%s\n' "$footer" | awk 'index($0, "exit: ") == 1 { sub(/^exit: /, ""); print; exit }')
  fin=$(printf '%s\n' "$footer" | awk 'index($0, "finished: ") == 1 { sub(/^finished: /, ""); print; exit }')
  by=$(printf '%s\n' "$footer" | awk 'index($0, "bytes: ") == 1 { sub(/^bytes: /, ""); print; exit }')
  if [ -z "$ex" ] || [ -z "$fin" ] || [ -z "$by" ]; then printf 'NO-FOOTER\x1f%s\x1f%s\n' "$ex" "$cmd_short"; return; fi
  if ! [[ "$ex" =~ ^[0-9]+$ ]] || [ "$ex" -gt 255 ]; then printf 'BAD-EXIT\x1f%s\x1f%s\n' "$ex" "$cmd_short"; return; fi
  local body_len=$((endoff - 1 - start))
  [ "$body_len" -lt 0 ] && body_len=0
  if ! [[ "$by" =~ ^[0-9]+$ ]] || [ "$body_len" -ne "$by" ]; then printf 'TRUNCATED(正文 %s 字节,bytes: %s)\x1f%s\x1f%s\n' "$body_len" "$by" "$ex" "$cmd_short"; return; fi
  printf 'OK\x1f%s\x1f%s\n' "$ex" "$cmd_short"
}

if [ "${#plan_ids[@]}" -eq 0 ]; then
  add_row "—" "—" "—" "—" "EMPTY-TABLE" "" "plan.md 无「测试用例」表或为空"
  need "EMPTY-TABLE plan.md 的「## 测试用例」表缺失或为空"
fi
if [ "${#rec_ids[@]}" -eq 0 ]; then
  add_row "—" "—" "—" "—" "EMPTY-TABLE" "" "implementation-round-$nn.md 无「测试结果」表或为空"
  need "EMPTY-TABLE implementation-round-$nn.md 的「## 测试结果」表缺失或为空"
fi

for id in "${plan_ids[@]}"; do
  ptier=${plan_tier[$id]}
  if [ -z "${rec_tier[$id]+x}" ]; then
    add_row "$id" "$ptier" "—" "—" "MISSING-ROW" "" "plan 有此用例,记录无"
    need "$id:MISSING-ROW 实现记录缺少该用例行(plan 档位 $ptier)"
    continue
  fi
  rtier=${rec_tier[$id]}; result=${rec_result[$id]}; evcell=${rec_evidence[$id]}
  if [ "$rtier" != "$ptier" ]; then
    add_row "$id" "$rtier" "$result" "—" "TIER-MISMATCH" "" "plan 为 $ptier 档,记录写 $rtier"
    need "$id:TIER-MISMATCH 档位与 plan 不一致(plan $ptier,记录 $rtier),档位须照抄 plan"
    continue
  fi
  if [ "$result" = "blocked" ]; then
    add_row "$id" "$rtier" "$result" "—" "BLOCKED" "" "存在 blocked 项,须先经用户裁决"
    need "$id:BLOCKED 结果为 blocked,不得进入评审"
    continue
  fi
  if [ "$rtier" != "A" ]; then
    add_row "$id" "$rtier" "$result" "${evcell//|/\\|}" "评审核验" "" "按档位由评审核验"
    continue
  fi
  # A 档:提取证据单元格里的 *.log 文件名
  mapfile -t files < <(printf '%s\n' "$evcell" | grep -oE '[A-Za-z0-9_./-]+\.log' | sort -u)
  if [ "${#files[@]}" -eq 0 ]; then
    add_row "$id" "$rtier" "$result" "—" "NO-REF" "" "证据单元格未引用 *.log 文件"
    need "$id:NO-REF 证据单元格未引用任何 evidence.sh 产出的 *.log 文件"
    continue
  fi
  for f in "${files[@]}"; do
    name=${f##*/}
    IFS=$'\x1f' read -r mark ex cmd_short <<< "$(check_file "$task_dir/evidence/$name")"
    add_row "$id" "$rtier" "$result" "$name" "$mark" "$ex" "$cmd_short"
    case "$mark" in
      OK) ;;
      *) need "$id:evidence/$name → $mark" ;;
    esac
  done
done

for id in "${rec_ids[@]}"; do
  [ -z "${plan_tier[$id]+x}" ] || continue
  add_row "$id" "${rec_tier[$id]}" "${rec_result[$id]}" "${rec_evidence[$id]//|/\\|}" "EXTRA-ROW" "" "plan 无此用例,由评审做范围核对"
done

echo "机器核验(evidence-check,$task_rel,第 $nn 轮):"
echo
echo "| 编号 | 档位 | 结果 | 证据文件 | 机器核验 | exit | cmd |"
echo "|---|---|---|---|---|---|---|"
printf '%s\n' "${rows[@]}"
echo
if [ "$fail" -eq 1 ]; then
  echo "结论:未通过(补交清单见 stderr)。"
  { echo "补交清单:"; printf -- '- %s\n' "${todo[@]}"; } >&2
  exit 1
fi
echo "结论:全部 A 档证据结构完整,记录与 plan 用例清单一致。"
exit 0
