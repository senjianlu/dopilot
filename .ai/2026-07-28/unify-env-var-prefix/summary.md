---
task: unify-env-var-prefix
date: 2026-07-28
rounds: 4
verdict: pass
---

# 任务小结:统一部署环境变量到 `DOPILOT_` 前缀

用户部署时发现 `REDIS_PASSWORD` 未加 `DOPILOT_` 前缀。全仓扫描确认共 **4 个**
面向部署的环境变量违反命名约定,而 `docs/architecture/04-configuration.md`
早已把"常规部署用 `DOPILOT_*` 环境变量覆盖"写成架构事实——实现与已记录的
约定不一致。本任务把 4 个变量全部改名,并把"部署环境变量一律 `DOPILOT_`
前缀"落为持久约定。

改名对照(破坏性变更,不留旧名兜底):

| 现名 | 改为 |
|---|---|
| `REDIS_PASSWORD` | `DOPILOT_REDIS_PASSWORD` |
| `REDIS_HOST` | `DOPILOT_REDIS_HOST` |
| `AGENT_ID` | `DOPILOT_AGENT_ID` |
| `AGENT_WORKDIR` | `DOPILOT_AGENT_WORKDIR` |

确认不改(经核实):`NEXT_PUBLIC_API_BASE`(Next.js 强制前缀)、CI 专用变量
(`DOCKER_PLATFORMS`/`DISPATCH_TOKEN`/`DOCKERHUB_USERNAME` 等,不进容器)、
`E2E_*` 测试变量、smoke 脚本内的 shell 局部量、agent 测试里作为模块常量的
`AGENT_ID`。

## 改动

| 文件 | 摘要 |
|---|---|
| `apps/agent/dopilot_agent/config/loader.py` | env 覆盖改读 `DOPILOT_AGENT_ID` / `DOPILOT_AGENT_WORKDIR`;docstring 映射表同步;补注前缀约定与「同名复用 protocol runtime context 键」的口径 |
| `apps/agent/tests/test_config.py` | 全部 env 名改新名;新增 `test_legacy_unprefixed_env_names_have_no_effect`(只设旧名时仍取 TOML 值) |
| `apps/agent/tests/test_healthcheck.py` | `_use_config()` 隔离元组改新名;新增 `test_use_config_isolates_deployment_env_overrides`(污染环境下加载缺 `agent_id` 的 TOML 必须抛 `ConfigError`) |
| `apps/agent/tests/test_python_wheel.py` | 新增 `test_wheel_run_runtime_context_beats_inherited_agent_env` 与非平凡性对照 `test_wheel_run_inherits_agent_env_without_runtime_context` |
| `deploy/docker/Dockerfile` | `ENV DOPILOT_AGENT_WORKDIR=/agent-data`;注释同步 |
| `deploy/docker/docker-compose.yml` | 3 个 agent 的两个 env + 6 处密码替换 + 顶部 env 说明 |
| `deploy/docker/docker-compose.server.yml` | 3 处密码替换 + 顶部 env 说明 |
| `deploy/docker/docker-compose.agent.yml` | 4 个变量全改(含 `:?` 快速失败与 `:-` 默认值)+ 必填/可选清单 + Deploy 示例 + 混合升级警告 |
| `deploy/kubernetes/agent/statefulset.yaml` | 两个 env 键改名,保持 `fieldRef: metadata.name`;反亲和注释里的陈旧引用一并更新 |
| `deploy/kubernetes/agent/README.md` | 表格描述改 `DOPILOT_AGENT_ID` |
| `README.md` / `README.zh-CN.md` | `.env` 样例、agent 接入命令行;新增前缀约定 + 升级须同时 `docker compose pull` 的警告 |
| `docs/architecture/04-configuration.md` | 新增「环境变量命名:`DOPILOT_` 前缀无例外」小节(三类豁免、`DOPILOT_AGENT_ID` 同名口径、混合升级警告);`[agent]` 行补两个 env 名 |

共 13 个文件。**产品行为变化仅限环境变量名**:TOML 字段名、env > TOML 的优先级、
`:?`/`:-` 语义、K8s 每 Pod 唯一 id 机制均未变。

### 关键设计裁定:`DOPILOT_AGENT_ID` 与 protocol runtime context 同名

`packages/protocol/dopilot_protocol/execution.py:13` 已用 `DOPILOT_AGENT_ID`
作为交给用户工作负载的 runtime context 键。本任务**刻意复用同名**而非另起
别名:二者表达同一事实("本 agent 的 id"),且由构造必然相等(agent 只消费
寻址到自己 id 的命令流);子进程侧仍取 runtime context 值(wheel runner 在
合并子进程环境时最后覆盖)。TC-09/TC-09b 专项守护该优先级。

## 评审历程

plan 阶段(上限 8,用户明确放宽;实际用 4 轮):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan-01 | fail | major:表格里为规避管道符写的 `\|` 在 ERE 中是字面量,TC-03/TC-06 命令实际失效,且 TC-03 把退出码 1 当成功会假通过 |
| plan-02 | fail | major:漏改 `test_healthcheck.py` 的环境隔离元组(用元组循环操作 env,躲过按名 grep)。查证此点时顺带发现 `DOPILOT_AGENT_ID` 已被 protocol 占用,遂在方案中裁定同名复用并加守护用例 |
| plan-03 | pass | 无 |
| plan-04 | pass | 实现层评审判 plan-blocker 后退回重写 TC-03 契约,重评通过、问题清单为空 |

实现层(上限 8,用户明确放宽;实际用 4 轮):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| impl-01 | fail | **plan-blocker**:TC-03 的"文本零残留"与本方案要求的"文档写出旧名升级提示"互斥(提示必须点名旧变量)。另 blocker:TC-03/TC-06 证据缺命令与退出码;major:"使用形态"正则不匹配 markdown 反引号,`deploy/kubernetes/agent/README.md` 的改名实际未被任何断言保护 |
| impl-02 | fail | blocker:实现记录 TC-08 写 `144 passed` 而日志为 `145`(第 01 轮数字误抄,当时 TC-09b 尚未加入);blocker:TC-03 第 ③ 组 `FILES` 漏 `test_config.py` / `test_python_wheel.py` |
| impl-03 | fail | blocker:`run-all.sh` 用 `"$*"` 打印命令,丢失 `-k "runtime_context or inherit"` 的参数边界,照抄日志无法复现 |
| impl-04 | **pass** | 无(无 blocker/major/minor) |

按 plan-blocker 规则,impl-01 后未自行进入修复轮,而是把问题原样交用户裁决,
由用户决定退回方案阶段并放宽轮次上限。

### 测试

11 条用例全 A 档、全 pass,C 档 0 条,含 5 条异常/边界路径:旧名失效(TC-02)、
缺变量时 compose `:?` 快速失败(TC-05)、污染环境下的隔离(TC-08)、回退副本
必须失败的反向自检(TC-08b)、runtime context 覆盖优先级及其非平凡性对照
(TC-09/TC-09b)。证据在 `evidence/`,每份含完整命令(逐参数加引号,可直接
复跑)、合流的 stdout/stderr、末行 `EXIT=<n>`。

`ruff check apps packages` 通过;`pytest apps/agent packages/protocol` 214 passed;
污染环境下 `pytest apps/agent` 145 passed。

TC-03 的收口脚本做 5 组断言 + 反向自检:使用形态残留 0、逐文件旧名→新名映射
(按任意形态取 HEAD 基线,含 markdown 反引号)、各文件废弃说明预算核对、agent
测试目录集合相等。

## 遗留 minor 及处置

最后一轮(impl-04)问题清单为空,**无遗留 minor**。

## 需用户注意(部署侧)

1. **破坏性变更**:`.env` / K8s 清单里 4 个变量名需加前缀。对当前部署而言就是
   `REDIS_PASSWORD=` → `DOPILOT_REDIS_PASSWORD=`。
2. **改名与拉镜像必须同批做**:只更新 compose 而不 `docker compose pull`,旧镜像
   的代码只认旧名,`agent_id` 会静默回落到烤进镜像的 TOML 值,导致一体栈三个
   agent 共用同一 id——症状隐蔽(节点列表少节点、命令分配错乱)且探针不报错。
   此点已写入 README ×2 与 `docs/architecture/04-configuration.md`。
3. 本机 `.venv` 的 editable 安装 `.pth` 指向仓库旧路径 `/home/rabbir/dopilot`
   (仓库被移动过),直接 `pytest` 会 `ModuleNotFoundError: dopilot_protocol`。
   与本任务无关,本次靠显式 `PYTHONPATH` 绕过、未改动 `.venv`;建议后续
   重建虚拟环境。
