---
task: unify-env-var-prefix
round: 02
date: 2026-07-28
---

# 实现记录:第 02 轮

修复轮上限:`impl_fix_max_rounds: 8`(**用户 2026-07-28 明确要求**把 plan 评审
与实现层修复上限各放宽到 8 轮,已写入 plan.md frontmatter 并在 plan 修订记录
中声明)。本轮 NN=02,未达上限。

## 本轮改动

**源码零改动**——`git status` 的源码改动集仍是第 01 轮的 13 个文件,内容未变
(本轮 diff 只落在 `.ai/` 内的检查脚本与证据)。第 01 轮评审的三条问题都不指向
产品代码:R-01 是方案契约措辞、R-02 是证据留存格式、R-03 是检查脚本的覆盖盲区。

| 文件 | 改动摘要 |
|---|---|
| `plan.md`(方案阶段已做) | TC-03 契约重写为 5 组断言(使用形态 / 废弃说明分开判定)+ 逐文件映射断言 + 各文件废弃说明预算表;新增 3.3「A 档证据留存格式」硬要求;TC-08 判别锚点、TC-09 非平凡性对照正式入方案;用例 9→11。plan 评审第 04 轮 pass(问题清单为空),用户已重新确认 |
| `evidence/tc03-legacy-name-scan.sh` | **按新契约重写**:①正则自检扩为 6 种使用形态正样本 + 5 条负样本(散文/反引号/新名);②使用形态残留 0;③**逐文件旧名→新名映射断言**(按任意形态取 HEAD 基线,含 markdown 反引号)——修 R-03;④废弃说明预算逐文件核对 + 逐行清单;⑤测试目录集合相等;⑥反向自检:把 k8s README 反引号里的名字改回旧名的副本,第 ③ 组必须判 FAIL |
| `evidence/tc04-compose-config.sh`(新增) | 把原先手敲的 compose 渲染检查脚本化,便于按 3.3 留证并可复跑;除原有断言外增加「一体栈 3 个 agent 的 `DOPILOT_AGENT_ID` 各不相同」 |
| `evidence/tc05-compose-failfast.sh`(新增) | 同上;增加「错误信息中不得出现裸旧名」断言(证明 `:?` 提示词已同步改名) |
| `evidence/run-all.sh`(新增) | 统一按 3.3 格式生成全部 10 份证据:每份含 `# 说明`、`$ cd`、`$ 完整命令`、合流的 stdout/stderr、**末行 `EXIT=<n>`** |
| `evidence/*.log`(10 份,全部重生成) | 修 R-02:文件自身含完整命令与显式退出码,不再依赖终端上下文 |
| `evidence/tc07-lint.log`(新增) | ruff 单独留证(原先与 pytest 挤在一份日志里,退出码无法分别核验) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | plan-blocker | **未在实现轮修复**——按 rawf-review 规则退回方案阶段:TC-03 的"文本零残留"与本方案要求的"文档写出旧名升级提示"互斥,已在 plan 3.1 正式重写为「使用形态残留 0」+「受控废弃说明预算」两类判定,plan 评审第 04 轮 pass、用户重新确认(`approved_at: 2026-07-28 15:27:07+0900`)。本轮据新契约重写脚本 |
| R-02 | blocker | 新增 `evidence/run-all.sh`,按 plan 3.3 重生成全部 10 份日志:每份首部写 `$ 完整命令`(含 `PYTHONPATH` 等前置环境变量)、正文为 `2>&1` 合流输出、**末行 `EXIT=<n>`**。ruff 与 pytest 拆成两份日志,退出码可分别核验。实现记录中报告的退出码与各日志末行一致 |
| R-03 | major | 第 ③ 组「逐文件旧名→新名映射断言」按**任意形态**(含 markdown 反引号)取 `git show HEAD:<file>` 基线:某文件 HEAD 用过 `X`,工作区就必须出现 ≥1 次 `DOPILOT_X`。`deploy/kubernetes/agent/README.md` 现被真正覆盖(日志:`AGENT_ID HEAD旧名=1 -> 现新名=1`),保持旧名/误删/正确改名三种情况可区分。并加第 ⑥ 组反向自检:把该文件反引号里的名字改回旧名的副本,第 ③ 组确实判 FAIL(`HEAD旧名=1 -> 现新名=0`),证明盲区已消除而非换个写法绕过 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-agent-config-pytest.log`(21 passed,`EXIT=0`) |
| TC-02 | A | pass | 同上日志 `test_legacy_unprefixed_env_names_have_no_effect PASSED` |
| TC-03 | A | pass | `evidence/tc03-legacy-name-scan.log`(`RESULT: PASS`,`EXIT=0`);5 组断言 + 第 ⑥ 组反向自检全通过;第 ③ 组逐文件逐变量列出 HEAD→现状映射,第 ④ 组 8 个文件预算全部"实际=预算"并附 10 行提及清单 |
| TC-04 | A | pass | `evidence/tc04-compose-config.log`(`RESULT: PASS`,`EXIT=0`):三份 compose 解析退出码均 0、渲染后无裸旧名 key、密码进入 `DOPILOT_REDIS_URL`、两份含 redis 的 `--requirepass` 与 URL 同源、agent 栈 URL 由新的两个变量正确拼出、一体栈 3 个 agent id 互不相同 |
| TC-05 | A | pass | `evidence/tc05-compose-failfast.log`(`RESULT: PASS`,`EXIT=0`):两者皆缺时退出码 1 且报 `required variable DOPILOT_REDIS_PASSWORD is missing a value: set DOPILOT_REDIS_PASSWORD or DOPILOT_REDIS_URL`、错误信息不含裸旧名;对照组补 `DOPILOT_REDIS_URL` 后退出码 0 |
| TC-06 | A | pass | `evidence/tc06-k8s-env-check.log`(`RESULT: PASS`,`EXIT=0`),含反向自检 |
| TC-07 | A | pass | `evidence/tc07-lint.log`(`All checks passed!`,`EXIT=0`)+ `evidence/tc07-lint-and-tests.log`(214 passed,`EXIT=0`) |
| TC-08 | A | pass | `evidence/tc08-polluted-env-pytest.log`(污染三个变量下 144 passed,`EXIT=0`) |
| TC-08b | A | pass | `evidence/tc08-reverse-selfcheck.log`(`RESULT: PASS`,`EXIT=0`):回退副本上锚点用例确实 `DID NOT RAISE ConfigError` 而失败;sha256 比对证明工作区已还原 |
| TC-09 | A | pass | `evidence/tc09-runtime-context-precedence.log`(3 passed,`EXIT=0`) |
| TC-09b | A | pass | 同上日志 `test_wheel_run_inherits_agent_env_without_runtime_context PASSED` |

`blocked` 项:无。C 档:0 条(plan 声明 11 条全 A 档,未下调任何档位)。
所有日志末行退出码与本表报告一致(可用 `tail -1 evidence/*.log` 复核)。

## 与方案的偏差

无。

第 01 轮记录的 4 条偏差已全部消解:

1. TC-03 判据(原偏差 1)——已在方案阶段正式重写契约,不再是偏差;
2. TC-08 判别锚点(原偏差 2)——锚点用例与"`hc.main()` 退出码被 scrapyd 探针
   掩盖、不可作锚点"的实测事实已写入 plan TC-08 行;
3. TC-09 非平凡性对照(原偏差 3)——已作为 TC-09b 正式入方案;
4. `PYTHONPATH`(原偏差 4)——本机 `.venv` 的 editable 安装 `.pth` 指向仓库旧
   路径 `/home/rabbir/dopilot`(仓库被移动过),属**与本任务无关的既有环境
   问题**;已按 plan 3.3 把该前置环境变量写进每份证据的命令行,未改动 `.venv`
   或任何仓库配置。
