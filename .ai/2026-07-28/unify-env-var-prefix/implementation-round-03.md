---
task: unify-env-var-prefix
round: 03
date: 2026-07-28
---

# 实现记录:第 03 轮

修复轮上限 `impl_fix_max_rounds: 8`(用户明确要求放宽,见 plan 修订记录),
本轮 NN=03,未达上限。

## 本轮改动

**源码零改动**——`git status` 的源码改动集仍是 13 个文件、内容与第 01 轮逐字
一致。第 02 轮评审的两条 blocker 分别指向实现记录里的一处数字误抄、以及 TC-03
检查脚本的覆盖清单缺两项,均不涉及产品代码。

| 文件 | 改动摘要 |
|---|---|
| `evidence/tc03-legacy-name-scan.sh` | 第 ③ 组 `FILES` 补入 `apps/agent/tests/test_config.py` 与 `apps/agent/tests/test_python_wheel.py`(修 R-02),使其与 plan「改动范围」的 13 个文件逐一对应;第 ④ 组显式跳过 `apps/*/tests/*` 并注明依据(plan 3.1 的范围排除项把测试目录交给第 ⑤ 组集合相等断言) |
| `evidence/*.log`(10 份,全部重生成) | 用 `evidence/run-all.sh` 按 plan 3.3 格式重跑,确保记录里引用的每个数字都来自本轮原始输出 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | **数字误抄,已改正**:TC-08 实际为 **145 passed**(`evidence/tc08-polluted-env-pytest.log:7`),第 02 轮记录写的 `144` 是从第 01 轮原样抄来的——第 01 轮时 TC-09b 的对照用例尚未加入,agent 套件确为 144,加入后变 145,我更新记录时漏改这个数。本轮所有引用数字改为**从日志现取**(`tail -1` 取退出码、`grep -oE '[0-9]+ passed'` 取数量)后填表,不再手抄:TC-01 = 21 passed、TC-07 = 214 passed、TC-08 = 145 passed、TC-09 = 3 passed,10 份日志末行均 `EXIT=0` |
| R-02 | blocker | **补全第 ③ 组覆盖**:`FILES` 原有 11 项,漏了本次改动的 `test_config.py`、`test_python_wheel.py`,现补入(共 13 项 = plan 改动范围的 13 个文件)。重跑后日志新增两行映射结果:`test_config.py AGENT_ID HEAD旧名=11 -> 现新名=12`、`AGENT_WORKDIR HEAD旧名=11 -> 现新名=12`、`test_python_wheel.py AGENT_ID HEAD旧名=12 -> 现新名=5`。同时把第 ④ 组的预算核对显式跳过 `apps/*/tests/*` 并写明依据——plan 3.1 的范围排除项已规定测试目录由第 ⑤ 组集合相等断言收口(那里 `AGENT_ID` 是模块级普通常量,且 TC-02 反向用例必须引用旧名),故这是执行 plan 的既定分工,不是放宽预算 |

## 测试结果

数量与结论均取自本轮重生成的日志原文(见每行括注的日志位置)。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-agent-config-pytest.log`:`21 passed`,末行 `EXIT=0` |
| TC-02 | A | pass | 同上日志:`test_legacy_unprefixed_env_names_have_no_effect PASSED` |
| TC-03 | A | pass | `evidence/tc03-legacy-name-scan.log`:`RESULT: PASS`,末行 `EXIT=0`;5 组断言 + 第 ⑥ 组反向自检全通过;第 ③ 组现覆盖 13 个受影响文件(含本轮补入的两个测试文件);第 ④ 组 8 个文件"实际=预算"并附提及清单 |
| TC-04 | A | pass | `evidence/tc04-compose-config.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-05 | A | pass | `evidence/tc05-compose-failfast.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-06 | A | pass | `evidence/tc06-k8s-env-check.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-07 | A | pass | `evidence/tc07-lint.log`:`All checks passed!`,末行 `EXIT=0`;`evidence/tc07-lint-and-tests.log`:`214 passed`,末行 `EXIT=0` |
| TC-08 | A | pass | `evidence/tc08-polluted-env-pytest.log`:`145 passed`,末行 `EXIT=0` |
| TC-08b | A | pass | `evidence/tc08-reverse-selfcheck.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-09 | A | pass | `evidence/tc09-runtime-context-precedence.log`:`3 passed`,末行 `EXIT=0` |
| TC-09b | A | pass | 同上日志:`test_wheel_run_inherits_agent_env_without_runtime_context PASSED` |

`blocked` 项:无。C 档:0 条(plan 声明 11 条全 A 档,未下调任何档位)。

## 与方案的偏差

无。

第 ④ 组跳过 `apps/*/tests/*` 一事**不是偏差**:plan 3.1 的「范围排除项」原文即
"`apps/*/tests/`——**不做整目录零残留断言**……测试目录改为用第 ⑤ 组集合相等
断言精确收口"。本轮只是把这条既定分工在脚本里显式写出来(此前靠 `grep
--exclude-dir=tests` 隐式生效,补入两个测试文件到第 ③ 组后必须显式化)。
