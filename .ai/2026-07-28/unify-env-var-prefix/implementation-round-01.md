---
task: unify-env-var-prefix
round: 01
date: 2026-07-28
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/dopilot_agent/config/loader.py` | env 覆盖改读 `DOPILOT_AGENT_ID` / `DOPILOT_AGENT_WORKDIR`(`:99`、`:102`);docstring 映射表同步(`:59-60`);补注前缀约定与「同名复用 runtime context 键」的口径(`:89-98`) |
| `apps/agent/tests/test_config.py` | 全部 env 名改新名(11 处 delenv/setenv + `_clear_token_env` 元组);新增 `test_legacy_unprefixed_env_names_have_no_effect`——只设旧名时 `agent_id`/`workdir` 必须仍取 TOML 值 |
| `apps/agent/tests/test_healthcheck.py` | `_use_config()` 隔离元组改新名(`:36`)并注明理由;新增 `test_use_config_isolates_deployment_env_overrides`——污染环境下加载缺 `agent_id` 的 TOML 必须抛 `ConfigError`(见「与方案的偏差」第 2 条) |
| `apps/agent/tests/test_python_wheel.py` | 新增 `test_wheel_run_runtime_context_beats_inherited_agent_env`(冲突的 `DOPILOT_AGENT_ID` 在 agent 进程环境里时,子进程仍取 runtime context 值)与对照用例 `test_wheel_run_inherits_agent_env_without_runtime_context`(证明继承值确实到达子进程,前者非平凡通过) |
| `deploy/docker/Dockerfile` | `ENV DOPILOT_AGENT_WORKDIR=/agent-data`(`:132`);`:119` 注释同步 |
| `deploy/docker/docker-compose.yml` | 3 个 agent 的 `DOPILOT_AGENT_ID`/`DOPILOT_AGENT_WORKDIR`;6 处 `${DOPILOT_REDIS_PASSWORD:-…}`;顶部 env 文档块补前缀约定说明;`x-agent` 与 redis 注释同步 |
| `deploy/docker/docker-compose.server.yml` | 3 处 `${DOPILOT_REDIS_PASSWORD:-…}`;顶部 env 文档块改名并说明「加入本栈的 agent 须用同一密码」 |
| `deploy/docker/docker-compose.agent.yml` | 4 个变量全部改名(含 `${DOPILOT_REDIS_PASSWORD:?…}` 快速失败与 `${DOPILOT_REDIS_HOST:-host.docker.internal}` 默认值);顶部必填/可选清单、Deploy 示例、混合升级警告 |
| `deploy/kubernetes/agent/statefulset.yaml` | `- name: DOPILOT_AGENT_ID`(保持 `fieldRef: metadata.name`)/ `- name: DOPILOT_AGENT_WORKDIR`;`:59` 反亲和注释里的陈旧 `AGENT_ID` 引用一并更新 |
| `deploy/kubernetes/agent/README.md` | `:17` 表格描述改 `DOPILOT_AGENT_ID` |
| `README.md` | `.env` 样例 `DOPILOT_REDIS_PASSWORD`;agent 接入命令行两个变量改名;新增一段前缀约定 + 升级须同时 `docker compose pull` 的警告 |
| `README.zh-CN.md` | 同上(中文) |
| `docs/architecture/04-configuration.md` | 新增「环境变量命名:`DOPILOT_` 前缀无例外」小节(含三类豁免、`DOPILOT_AGENT_ID` 同名口径、混合升级警告);`[agent]` 行补两个 env 名 |

配套产物(`.ai/` 内,非源码):`evidence/tc03-legacy-name-scan.sh`、
`evidence/tc06-k8s-env-check.sh`、`evidence/tc08-reverse-selfcheck.sh`。

## 修复对照

不适用(第 01 轮)。plan 阶段 Codex 评审 3 轮(R-01 正则失效 / R-01 漏改
`test_healthcheck.py`),已在方案确认前就地修完,详见 `plan-review-round-0*.md`。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-agent-config-pytest.log`(21 passed,含改名后的 `test_agent_id_env_override` / `test_workdir_env_override`) |
| TC-02 | A | pass | 同上日志中 `test_legacy_unprefixed_env_names_have_no_effect PASSED`(只设 `AGENT_ID=legacy-id`/`AGENT_WORKDIR=/legacy` 时仍取 TOML 的 `from-toml` / `/agent-data`) |
| TC-03 | A | pass | `evidence/tc03-legacy-name-scan.log`(EXIT=0,`RESULT: PASS`;5 组断言全通过,10 个文件基线对比逐行列出) |
| TC-04 | A | pass | `evidence/tc04-compose-config.log`(三份 compose 各 EXIT=0;末尾断言段 `ASSERT_RESULT: PASS`——渲染后无裸旧名 key、密码进入 `DOPILOT_REDIS_URL`、redis `--requirepass` 与 URL 同源) |
| TC-05 | A | pass | `evidence/tc05-compose-failfast.log`(EXIT=1,报 `required variable DOPILOT_REDIS_PASSWORD is missing a value: set DOPILOT_REDIS_PASSWORD or DOPILOT_REDIS_URL`;并附「补 `DOPILOT_REDIS_URL` 即解除」的对照) |
| TC-06 | A | pass | `evidence/tc06-k8s-env-check.log`(EXIT=0,`RESULT: PASS`;含反向自检:回退副本上裸旧键检测确实命中,断言非恒真) |
| TC-07 | A | pass | `evidence/tc07-lint-and-tests.log`(`ruff check apps packages` EXIT=0;`pytest apps/agent packages/protocol` 214 passed EXIT=0) |
| TC-08 | A | pass | `evidence/tc08-polluted-env-pytest.log`(污染 `DOPILOT_AGENT_ID`/`DOPILOT_AGENT_WORKDIR`/`DOPILOT_REDIS_PASSWORD` 下 144 passed EXIT=0);判别力见 `evidence/tc08-reverse-selfcheck.log`(EXIT=0) |
| TC-09 | A | pass | `evidence/tc09-runtime-context-precedence.log`(3 passed EXIT=0:precedence 用例 + 非平凡性对照 + 既有 operator env 方向用例) |

`blocked` 项:无。C 档:0 条(plan 声明 9 条全 A 档,未下调任何档位)。

## 与方案的偏差

### 1. TC-03 残留判定改为「使用形态」+「散文提及白名单」两组断言(判据加强)

- **偏了什么**:plan 3.1/TC-03 写的是"部署面旧名文本残留为 0"。实现后改为:
  (A) **使用形态**残留必须为 0——变量替换 `${X}`、YAML 键 `X:`、
  k8s `- name: X`、env 赋值 `X=`、字符串字面量 `"X"`;(B) 其余"散文提及"
  逐条打印,且只允许出现在废弃提示白名单文件内,白名单外任何文件出现裸旧名
  即 FAIL。
- **为什么**:plan 自身要求 README / compose / 架构文档写出"旧名已废弃、
  需改名"的升级提示,而这类提示**必须点名旧变量**才有用(用户要照着改
  `.env`)。纯文本扫描会把这 10 行有意的提示判成残留,两个要求直接互斥。
- **影响范围**:判据不是放宽而是变细并增强——除使用形态零残留外,额外多了
  白名单集合断言。实际残留使用形态为 0(见日志第 2 组),10 行散文提及全部
  落在白名单内并逐行列出可复核。
- 该偏差同时写在脚本头注释里(`evidence/tc03-legacy-name-scan.sh:5-12`)。

### 2. TC-08 的判别锚点换成新增的加载阶段用例(原锚点实测无判别力)

- **偏了什么**:plan TC-08 括注"尤其 `test_healthcheck` 的『缺 agent_id 应
  失败』用例不会被宿主机环境救活"。第一次跑反向自检时**实测该说法不成立**:
  把隔离元组回退为旧名、在污染环境下重跑,`test_healthcheck_fails_on_bad_config`
  **仍然通过**。
- **实际机理(已查证)**:污染确实绕过了配置校验——直接探测 loader 显示,
  保留 `DOPILOT_AGENT_ID=polluted` 时,缺 `agent_id` 的 TOML **加载成功**
  (`agent_id='polluted'`),清掉才抛 `ConfigError`。但该用例断言的是
  `hc.main() == 1`,而配置加载成功后紧随的 scrapyd 探针照样失败、仍返回 1。
  也就是说**退出码掩盖了隔离已失效的事实**——用例"为错误的原因通过",
  正是第 02 轮评审 R-01 预警的情形,只是外部表现看不出来。
- **怎么处理**:新增 `test_use_config_isolates_deployment_env_overrides`,
  直接断言**配置加载阶段**(污染下必须抛 `ConfigError`),把污染真正落地的
  位置钉住;反向自检改以它为锚点,回退副本上确实失败(`DID NOT RAISE
  ConfigError`),证明 TC-08 现在有判别力而非恒真。
- **影响范围**:TC-08 本体(污染环境全量 agent 测试全绿)按 plan 原样通过,
  未改其档位与预期结果;补充的是判别力证明与一条新的常驻回归用例。

### 3. TC-09 增补一条非平凡性对照用例

plan 只要求"子进程取 runtime context 值"。若继承的 `DOPILOT_AGENT_ID` 根本
到不了子进程,该断言会平凡通过。故补
`test_wheel_run_inherits_agent_env_without_runtime_context`:不带 runtime
context 时子进程确实读到继承值,从而证明前者检验的是**覆盖优先级**。

### 4. 执行环境:显式设 `PYTHONPATH`(与本次改动无关的既有环境问题)

本机 `.venv` 的 editable 安装 `.pth` 指向 `/home/rabbir/dopilot`,而仓库实际在
`/home/rabbir/Projects/dopilot`(仓库被移动过),直接 `pytest` 会
`ModuleNotFoundError: No module named 'dopilot_protocol'`。故所有 pytest 命令前
显式设 `PYTHONPATH` 指向三个包目录;这只影响导入解析,不改变被测行为,已在各
证据日志头部注明。**未**改动 `.venv` 或任何仓库配置。
