#!/usr/bin/env bash
# 按 plan.md 3.3 的 A 档证据留存格式重新生成全部证据文件:
# 每份日志自身含「$ 完整命令」+ 合流的 stdout/stderr + 末行 EXIT=<n>。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail
export LC_ALL=C

E=.ai/2026-07-28/unify-env-var-prefix/evidence
PY=.venv/bin/python
# 本机 .venv 的 editable 安装 .pth 指向仓库旧路径 /home/rabbir/dopilot(仓库被
# 移动过),不设 PYTHONPATH 会 ModuleNotFoundError: dopilot_protocol。
# 这只影响导入解析,不改变被测行为。
PP=$PWD/apps/agent:$PWD/packages/protocol:$PWD/apps/server

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

# cap <log> <note> <cmd...>:执行并把命令/输出/退出码完整写进 <log>。
# 命令行用 ${*@Q}(bash 4.4+)**逐参数加引号**输出,而非 "$*":后者会丢掉参数
# 边界,例如 -k "runtime_context or inherit" 会被打印成三个独立词,照抄日志
# 重跑得到的是另一条命令(第 03 轮评审 R-01)。逐参数加引号后可直接复制复跑。
cap() {
  local log=$1 hint=$2; shift 2
  {
    [ -n "$hint" ] && printf '# %s\n' "$hint"
    printf '$ cd %s\n' "$PWD"
    printf '$ %s\n' "${*@Q}"
    "$@" 2>&1
    printf 'EXIT=%s\n' "$?"
  } > "$log"
  local rc; rc=$(tail -1 "$log" | sed 's/^EXIT=//')
  printf '%-46s EXIT=%s\n' "$(basename "$log")" "$rc"
  [ "$rc" = 0 ]
}

overall=0

cap "$E/tc01-agent-config-pytest.log" \
  "TC-01/TC-02:agent 配置加载器用例(含 TC-02 反向用例 test_legacy_unprefixed_env_names_have_no_effect)。PYTHONPATH=$PP" \
  env -u DOPILOT_AGENT_ID -u DOPILOT_AGENT_WORKDIR "PYTHONPATH=$PP" \
  "$PY" -m pytest apps/agent/tests/test_config.py -v || overall=1

cap "$E/tc03-legacy-name-scan.log" \
  "TC-03:旧名收口检查,5 组断言 + 反向自检(契约见 plan.md 3.1 修订版)" \
  bash "$E/tc03-legacy-name-scan.sh" || overall=1

cap "$E/tc04-compose-config.log" \
  "TC-04:三份 compose 用新变量名渲染 + 渲染结果断言" \
  bash "$E/tc04-compose-config.sh" || overall=1

cap "$E/tc05-compose-failfast.log" \
  "TC-05:缺 DOPILOT_REDIS_PASSWORD 时 compose :? 快速失败" \
  bash "$E/tc05-compose-failfast.sh" || overall=1

cap "$E/tc06-k8s-env-check.log" \
  "TC-06:K8s StatefulSet env 键名 + fieldRef 关联 + 反向自检" \
  bash "$E/tc06-k8s-env-check.sh" || overall=1

cap "$E/tc07-lint.log" \
  "TC-07(前半):ruff" \
  "$PY" -m ruff check apps packages || overall=1

cap "$E/tc07-lint-and-tests.log" \
  "TC-07(后半):agent + protocol 全量测试。PYTHONPATH=$PP;ruff 结果见 tc07-lint.log" \
  env -u DOPILOT_AGENT_ID -u DOPILOT_AGENT_WORKDIR "PYTHONPATH=$PP" \
  "$PY" -m pytest apps/agent packages/protocol -q || overall=1

cap "$E/tc08-polluted-env-pytest.log" \
  "TC-08:故意用常规部署变量污染环境跑全量 agent 测试;判别力见 tc08-reverse-selfcheck.log。PYTHONPATH=$PP" \
  env DOPILOT_AGENT_ID=polluted DOPILOT_AGENT_WORKDIR=/polluted \
  DOPILOT_REDIS_PASSWORD=polluted "PYTHONPATH=$PP" \
  "$PY" -m pytest apps/agent -q || overall=1

cap "$E/tc08-reverse-selfcheck.log" \
  "TC-08b:回退隔离元组后锚点用例必须失败(证明 TC-08 非恒真)" \
  bash "$E/tc08-reverse-selfcheck.sh" || overall=1

cap "$E/tc09-runtime-context-precedence.log" \
  "TC-09/TC-09b:runtime context 覆盖优先于继承的 agent 进程环境 + 非平凡性对照。PYTHONPATH=$PP" \
  env "PYTHONPATH=$PP" "$PY" -m pytest apps/agent/tests/test_python_wheel.py -v \
  -k "runtime_context or inherit" || overall=1

echo
[ "$overall" -eq 0 ] && echo "ALL EVIDENCE REGENERATED: all EXIT=0" \
  || echo "ALL EVIDENCE REGENERATED: 有用例非 0 退出,见上"
exit "$overall"
