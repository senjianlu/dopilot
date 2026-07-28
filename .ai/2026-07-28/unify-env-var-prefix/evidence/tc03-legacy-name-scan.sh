#!/usr/bin/env bash
# TC-03:部署环境变量旧名收口检查。契约见 plan.md 3.1(修订版,5 组断言):
#   ① 正则自检:ANY_OLD 只命中裸旧名;USE_OLD 覆盖 6 种使用形态且不误伤
#      散文/markdown 反引号/DOPILOT_ 前缀名
#   ② 使用形态残留必须为 0
#   ③ 逐文件旧名→新名映射断言(任意形态,含 markdown 反引号)——修 R-03:
#      旧版只看"使用形态",反引号里的旧名不计,导致 k8s README 报"基线 0 /
#      现新名 0",保持旧名/误删/正确改名三种情况都能通过
#   ④ 废弃说明预算:各文件裸旧名出现次数 <= 声明预算,预算外文件为 0
#   ⑤ agent 测试目录含旧名的文件集合与允许清单相等
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail
export LC_ALL=C

NAMES='AGENT_ID|AGENT_WORKDIR|REDIS_PASSWORD|REDIS_HOST'
ANY_OLD="\\b($NAMES)\\b"
# 6 种使用形态:替换 / YAML 键 / k8s `- name: X` / env 赋值 / 引号字面量 / Dockerfile ENV。
# k8s 与 Dockerfile 形态必须单列:`- name: AGENT_WORKDIR` 与 `ENV X value` 的
# 变量名后都没有冒号或等号,套用 YAML/赋值形态会漏判(第 01 轮实测踩到过)。
SUB='\$\{?'
K8S='^[[:space:]]*-[[:space:]]*name:[[:space:]]*'
ENVD='^ENV[[:space:]]+'
USE_OLD="($SUB($NAMES)\\b|^[[:space:]]*($NAMES):|$K8S($NAMES)[[:space:]]*\$|\\b($NAMES)=|[\"']($NAMES)[\"']|$ENVD($NAMES)\\b)"

SCOPE=(deploy configs docs scripts examples packages .github/workflows
       apps/agent/dopilot_agent apps/server/dopilot_server
       README.md README.zh-CN.md)
EXCL=(--exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.venv
      --exclude-dir=__pycache__ --exclude-dir=tests)

# 第 ③ 组:本次改名触及的**全部**文件(含 SCOPE 之外的 agent 测试文件)。
# 须与 plan.md「改动范围」的 13 个文件逐一对应——第 02 轮评审 R-02 指出漏了
# test_config.py 与 test_python_wheel.py,已补入。
FILES=(apps/agent/dopilot_agent/config/loader.py
       apps/agent/tests/test_config.py
       apps/agent/tests/test_healthcheck.py
       apps/agent/tests/test_python_wheel.py
       deploy/docker/Dockerfile
       deploy/docker/docker-compose.yml
       deploy/docker/docker-compose.server.yml
       deploy/docker/docker-compose.agent.yml
       deploy/kubernetes/agent/statefulset.yaml
       deploy/kubernetes/agent/README.md
       docs/architecture/04-configuration.md
       README.md README.zh-CN.md)

# 第 ④ 组:废弃说明预算(plan.md 3.1 声明的裸旧名出现次数上限)。
# 预算外的任何文件一律 0。改预算须回方案阶段重评,不得在实现轮放宽。
budget_of() {
  case "$1" in
    README.md|README.zh-CN.md)                     echo 4 ;;
    deploy/docker/docker-compose.agent.yml)        echo 4 ;;
    deploy/docker/docker-compose.yml)              echo 2 ;;
    deploy/docker/docker-compose.server.yml)       echo 1 ;;
    deploy/kubernetes/agent/statefulset.yaml)      echo 2 ;;
    docs/architecture/04-configuration.md)         echo 2 ;;
    apps/agent/dopilot_agent/config/loader.py)     echo 2 ;;
    *)                                             echo 0 ;;
  esac
}

# 第 ⑤ 组:改完后仍允许含旧名的 agent 测试文件
#   test_config.py -> TC-02 反向用例必须引用旧名
#   其余 4 个      -> 模块级普通常量 AGENT_ID = "agent-x"
ALLOWED_TESTS=(apps/agent/tests/test_command_consumer.py
               apps/agent/tests/test_config.py
               apps/agent/tests/test_event_outbox.py
               apps/agent/tests/test_log_publisher.py
               apps/agent/tests/test_python_wheel.py)

fail=0
note() { printf '%s\n' "$*"; }
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { fail=1; printf 'FAIL  %s\n' "$*"; }
# occ <pattern> <file>:出现次数(非行数)
occ() { grep -oE "$1" "$2" 2>/dev/null | wc -l; }
occ_head() { git show "HEAD:$2" 2>/dev/null | grep -oE "$1" | wc -l; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== ① 正则自检 =="
probe=$(printf '%s\n' 'AGENT_ID' 'DOPILOT_AGENT_ID' 'AGENT_IDS' \
        'REDIS_PASSWORD' 'DOPILOT_REDIS_PASSWORD' | grep -nE "$ANY_OLD")
printf '%s\n' "$probe" | sed 's/^/    /'
[ "$probe" = "$(printf '1:AGENT_ID\n4:REDIS_PASSWORD')" ] \
  && ok "ANY_OLD 只命中裸旧名(第 1、4 行;不误伤 DOPILOT_ 前缀名与 AGENT_IDS)" \
  || bad "ANY_OLD 行为不符预期,后续断言不可信"

note ""
note "  USE_OLD 正样本(6 种使用形态,应逐条命中):"
pos=$(printf '%s\n' \
  '  DOPILOT_REDIS_URL: redis://:${REDIS_PASSWORD:-x}@redis:6379/0' \
  '      AGENT_ID: scrapy-agent-1' \
  '            - name: AGENT_WORKDIR' \
  '  REDIS_PASSWORD=<server-redis-pass> \' \
  '    env_agent_id = os.environ.get("AGENT_ID")' \
  'ENV AGENT_WORKDIR /agent-data')
printf '%s\n' "$pos" | grep -nE "$USE_OLD" | sed 's/^/    /'
npos=$(printf '%s\n' "$pos" | grep -cE "$USE_OLD")
[ "$npos" -eq 6 ] && ok "6 种使用形态全部命中" || bad "使用形态覆盖不足(命中 $npos/6)"

note ""
note "  USE_OLD 负样本(散文 / markdown 反引号 / 新名,应全部不命中):"
neg=$(printf '%s\n' \
  '# the bare AGENT_ID / AGENT_WORKDIR names are gone with no fallback' \
  '版本仍在用裸名(`REDIS_PASSWORD`、`REDIS_HOST`、`AGENT_ID`)' \
  '| `statefulset.yaml` | ... `AGENT_ID` 取 pod 名 ... |' \
  '      DOPILOT_AGENT_ID: scrapy-agent-1' \
  '            - name: DOPILOT_AGENT_WORKDIR')
printf '%s\n' "$neg" | grep -nE "$USE_OLD" | sed 's/^/    HIT(不应出现) /'
nneg=$(printf '%s\n' "$neg" | grep -cE "$USE_OLD")
[ "$nneg" -eq 0 ] && ok "负样本全部未命中(反引号/散文归入第 ③④ 组判定)" \
  || bad "负样本被误判为使用形态($nneg 条)"

note ""
note "== ② 使用形态残留必须为 0 =="
hits=$(grep -rnE "$USE_OLD" "${SCOPE[@]}" "${EXCL[@]}" 2>/dev/null)
if [ -z "$hits" ]; then
  ok "扫描范围内无旧名以使用形态残留"
else
  printf '%s\n' "$hits" | sed 's/^/  HIT  /'
  bad "仍有旧名被实际使用(见上)"
fi

note ""
note "== ③ 逐文件旧名→新名映射断言(任意形态,含 markdown 反引号) =="
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { bad "$f 不存在"; continue; }
  mapped=0
  for n in AGENT_ID AGENT_WORKDIR REDIS_PASSWORD REDIS_HOST; do
    h=$(occ_head "\\b$n\\b" "$f")
    [ "$h" -eq 0 ] && continue
    w=$(occ "\\bDOPILOT_$n\\b" "$f")
    printf '  %-46s %-16s HEAD旧名=%s -> 现新名=%s\n' "$f" "$n" "$h" "$w"
    [ "$w" -ge 1 ] || bad "$f:HEAD 用过 $n,工作区却找不到 DOPILOT_$n(保持旧名或被误删)"
    mapped=1
  done
  [ "$mapped" -eq 1 ] || printf '  %-46s (HEAD 无旧名,无需映射)\n' "$f"
done

note ""
note "== ④ 废弃说明预算:裸旧名出现次数 <= 声明预算,预算外文件为 0 =="
mention_files=$(grep -rlE "$ANY_OLD" "${SCOPE[@]}" "${EXCL[@]}" 2>/dev/null | sort -u)
# 受影响文件即使不在 SCOPE(如 agent 测试文件)也一并计入预算核对
all_check=$(printf '%s\n%s\n' "$mention_files" "$(printf '%s\n' "${FILES[@]}")" | sort -u)
for f in $all_check; do
  [ -f "$f" ] || continue
  # apps/*/tests/ 不受预算约束:plan.md 3.1 的范围排除项明确把测试目录交给
  # 第 ⑤ 组集合相等断言(那里 AGENT_ID 是模块级普通常量,且 TC-02 的反向用例
  # 必须引用旧名)。此处跳过是执行 plan 的既定分工,不是放宽预算。
  case "$f" in apps/*/tests/*) continue ;; esac
  n=$(occ "$ANY_OLD" "$f"); b=$(budget_of "$f")
  [ "$n" -eq 0 ] && [ "$b" -eq 0 ] && continue
  printf '  %-46s 裸旧名出现=%s  预算=%s\n' "$f" "$n" "$b"
  [ "$n" -le "$b" ] || bad "$f 裸旧名出现 $n 次,超出预算 $b"
done
note "  逐行清单(供复核每处提及是否确为废弃说明):"
grep -rnE "$ANY_OLD" "${SCOPE[@]}" "${EXCL[@]}" 2>/dev/null | sed 's/^/    /'
[ "$fail" -eq 0 ] && ok "所有文件均在预算内(预算外文件裸旧名为 0)"

note ""
note "== ⑤ agent 测试目录:含旧名的文件集合必须与允许清单相等 =="
actual_tests=$(grep -rlE "$ANY_OLD" apps/agent/tests --exclude-dir=__pycache__ | sort)
expect_tests=$(printf '%s\n' "${ALLOWED_TESTS[@]}" | sort)
note "  实际:"; printf '%s\n' "$actual_tests" | sed 's/^/    /'
note "  允许:"; printf '%s\n' "$expect_tests" | sed 's/^/    /'
extra=$(comm -23 <(printf '%s\n' "$actual_tests") <(printf '%s\n' "$expect_tests"))
missing=$(comm -13 <(printf '%s\n' "$actual_tests") <(printf '%s\n' "$expect_tests"))
[ -z "$extra" ] || { printf '%s\n' "$extra" | sed 's/^/  UNEXPECTED  /'
  bad "有测试文件仍以旧名操作环境变量(疑似漏改)"; }
[ -z "$missing" ] || { printf '%s\n' "$missing" | sed 's/^/  GONE  /'
  bad "允许清单里的文件不再含旧名(清单已过期,须复核)"; }
[ -z "$extra" ] && [ -z "$missing" ] && ok "测试目录集合相等"
grep -qE '"DOPILOT_AGENT_ID", *"DOPILOT_AGENT_WORKDIR"' apps/agent/tests/test_healthcheck.py \
  && ok "test_healthcheck 隔离元组已改新名" || bad "test_healthcheck 隔离元组未改新名"

note ""
note "== ⑥ 反向自检:第 ③ 组断言对回退副本必须报错(证明非恒真) =="
tmpd=$(mktemp -d); trap 'rm -rf "$tmpd"' EXIT
cp deploy/kubernetes/agent/README.md "$tmpd/k8s-readme-reverted.md"
sed -i 's/`DOPILOT_AGENT_ID`/`AGENT_ID`/' "$tmpd/k8s-readme-reverted.md"
rev_new=$(occ '\bDOPILOT_AGENT_ID\b' "$tmpd/k8s-readme-reverted.md")
rev_head=$(occ_head '\bAGENT_ID\b' deploy/kubernetes/agent/README.md)
note "  回退副本(把反引号里的名字改回旧名):HEAD旧名=$rev_head -> 现新名=$rev_new"
{ [ "$rev_head" -ge 1 ] && [ "$rev_new" -eq 0 ]; } \
  && ok "第 ③ 组会对该副本判 FAIL => R-03 的反引号盲区确已修掉" \
  || bad "第 ③ 组对回退副本无反应,盲区仍在"

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
