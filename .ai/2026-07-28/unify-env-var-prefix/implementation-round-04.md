---
task: unify-env-var-prefix
round: 04
date: 2026-07-28
---

# 实现记录:第 04 轮

修复轮上限 `impl_fix_max_rounds: 8`(用户明确要求放宽),本轮 NN=04,未达上限。

## 本轮改动

**源码零改动**——源码改动集仍是 13 个文件、内容与第 01 轮逐字一致。本轮只改
证据生成器的命令行打印方式并重生成 10 份日志。

| 文件 | 改动摘要 |
|---|---|
| `evidence/run-all.sh` | `cap()` 打印命令行改用 `${*@Q}`(bash 4.4+,逐参数加引号)替代 `"$*"`,并注明原因 |
| `evidence/*.log`(10 份,全部重生成) | 命令行不再丢失参数边界,可直接复制复跑 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | `run-all.sh:23` 原用 `printf '$ %s\n' "$*"`,把参数拍平成一个空格分隔的字符串,`-k "runtime_context or inherit"` 因此被记成 `-k runtime_context or inherit`——照抄日志重跑会被拆成三个参数,命令不可复现。改为 `printf '$ %s\n' "${*@Q}"`,逐参数加引号(本机 bash 5.2.21 支持)。TC-09 日志现记为 `'-k' 'runtime_context or inherit'`。**已实测复现**:用 `sed -n "3s/^\$ //p"` 从日志第 3 行逐字取出命令并 `eval` 重跑,得到 `collected 25 items / 22 deselected / 3 selected`、`3 passed`、退出码 0,与日志内容一致。10 份日志的命令行均按此格式重生成 |

## 测试结果

数量与结论取自本轮重生成的日志原文。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-agent-config-pytest.log`:`21 passed`,末行 `EXIT=0` |
| TC-02 | A | pass | 同上日志:`test_legacy_unprefixed_env_names_have_no_effect PASSED` |
| TC-03 | A | pass | `evidence/tc03-legacy-name-scan.log`:`RESULT: PASS`,末行 `EXIT=0`;5 组断言 + 第 ⑥ 组反向自检全通过;第 ③ 组覆盖 13 个受影响文件;第 ④ 组 8 个文件"实际=预算" |
| TC-04 | A | pass | `evidence/tc04-compose-config.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-05 | A | pass | `evidence/tc05-compose-failfast.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-06 | A | pass | `evidence/tc06-k8s-env-check.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-07 | A | pass | `evidence/tc07-lint.log`:`All checks passed!`,末行 `EXIT=0`;`evidence/tc07-lint-and-tests.log`:`214 passed`,末行 `EXIT=0` |
| TC-08 | A | pass | `evidence/tc08-polluted-env-pytest.log`:`145 passed`,末行 `EXIT=0` |
| TC-08b | A | pass | `evidence/tc08-reverse-selfcheck.log`:`RESULT: PASS`,末行 `EXIT=0` |
| TC-09 | A | pass | `evidence/tc09-runtime-context-precedence.log`:`3 passed`,末行 `EXIT=0`;命令行已可逐字复跑(见修复对照) |
| TC-09b | A | pass | 同上日志:`test_wheel_run_inherits_agent_env_without_runtime_context PASSED` |

`blocked` 项:无。C 档:0 条(plan 声明 11 条全 A 档,未下调任何档位)。

## 与方案的偏差

无。
