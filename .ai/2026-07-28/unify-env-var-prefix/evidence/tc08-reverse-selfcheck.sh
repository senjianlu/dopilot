#!/usr/bin/env bash
# TC-08 反向自检:证明"污染环境跑全量 agent 测试"这条用例有判别力。
#
# 背景(第 1 次跑本脚本的实测发现,已记入 implementation-round-01.md):
# 原本打算用 test_healthcheck_fails_on_bad_config 做判别锚点,实测**不成立**——
# 即使隔离失效、污染的 DOPILOT_AGENT_ID 补上了 TOML 里故意缺失的 agent_id
# (配置因此加载成功),该用例的 hc.main() 仍返回 1,因为紧随其后的 scrapyd
# 探针也失败。即"退出码 1"掩盖了隔离已失效的事实。
# 故判别锚点改为 test_use_config_isolates_deployment_env_overrides:它直接断言
# **配置加载阶段**——污染下仍必须抛 ConfigError,这正是污染真正落地的位置。
#
# 做法:在临时副本上把 test_healthcheck.py 的隔离元组改回旧名,在污染环境下
# 重跑,期望该用例失败。跑完无条件还原,并与运行前的校验和比对断言已还原。
#
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail
export LC_ALL=C

F=apps/agent/tests/test_healthcheck.py
ANCHOR=test_use_config_isolates_deployment_env_overrides
BAK=$(mktemp)
fail=0
note() { printf '%s\n' "$*"; }
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
[ -x .venv/bin/python ] || { echo "找不到 .venv/bin/python" >&2; exit 2; }

# 本机 .venv 的 editable 安装指向仓库旧路径,显式补 PYTHONPATH(不改被测行为)
export PYTHONPATH=$PWD/apps/agent:$PWD/packages/protocol:$PWD/apps/server

cp -p "$F" "$BAK"
before=$(sha256sum < "$F")
restore() { cp -p "$BAK" "$F"; }
trap 'restore; rm -f "$BAK"' EXIT

note "== 0. 基线:改动后的工作区,在污染环境下该锚点用例必须通过 =="
set +e
DOPILOT_AGENT_ID=polluted DOPILOT_AGENT_WORKDIR=/polluted \
  .venv/bin/python -m pytest "$F::$ANCHOR" -q 2>&1 | tail -5
rc0=${PIPESTATUS[0]}
set -e
note "  退出码=$rc0"
[ "$rc0" -eq 0 ] && ok "现状下锚点用例通过(隔离有效)" || bad "现状下锚点用例就失败,须先修实现"

note ""
note "== 1. 回退副本:把隔离元组改回旧名 =="
sed -i 's/"DOPILOT_AGENT_ID", "DOPILOT_AGENT_WORKDIR"/"AGENT_ID", "AGENT_WORKDIR"/' "$F"
grep -nE '^[[:space:]]*for var in \(' "$F" | sed 's/^/    /'
grep -q '"AGENT_ID", "AGENT_WORKDIR"' "$F" \
  && ok "副本已回退为旧名" || bad "回退未生效,后续结论无效"

note ""
note "== 2. 污染环境下重跑锚点用例(期望失败) =="
set +e
DOPILOT_AGENT_ID=polluted DOPILOT_AGENT_WORKDIR=/polluted \
  .venv/bin/python -m pytest "$F::$ANCHOR" -q 2>&1 | tail -18
rc=${PIPESTATUS[0]}
set -e
note "  退出码=$rc"
[ "$rc" -ne 0 ] \
  && ok "回退副本在污染环境下确实失败 => 该断言有判别力,不是恒真" \
  || bad "回退副本仍通过 => 断言无判别力,须重新设计"

note ""
note "== 3. 还原并与运行前校验和比对 =="
restore
after=$(sha256sum < "$F")
note "  before=$before"
note "  after =$after"
[ "$before" = "$after" ] && ok "$F 已按运行前内容还原" || bad "$F 未正确还原"
grep -q '"DOPILOT_AGENT_ID", "DOPILOT_AGENT_WORKDIR"' "$F" \
  && ok "隔离元组仍为新名" || bad "隔离元组未还原为新名"

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
