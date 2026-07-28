---
status: approved
task: unify-env-var-prefix
date: 2026-07-28
approved_at: 2026-07-28 15:27:07+0900
plan_review_max_rounds: 8
impl_fix_max_rounds: 8
---

# 方案:统一部署环境变量到 `DOPILOT_` 前缀

## 修订记录

| 时间 | 事件 |
|---|---|
| 2026-07-28 14:52:05+0900 | 初次确认(status→approved),plan 评审 3 轮 pass |
| 2026-07-28 15:27:07+0900 | 修订后重新确认(status→approved),plan 评审第 04 轮 pass、问题清单为空 |
| 2026-07-28(本次修订) | 实现层评审 `review-round-01-fail.md` 判 **plan-blocker R-01**:TC-03 的"文本零残留"契约与本方案自身要求的"README/架构文档写出旧名升级提示"互斥(升级提示必须点名旧变量)。实现阶段自行改判据不算修复已批准契约,故退回方案阶段正式重写 TC-03(见 3.1),status→draft 重走确认闸 |

轮次上限:**用户 2026-07-28 明确要求**把 plan 评审与实现层修复的轮次上限
各放宽到 **8 轮**,故 frontmatter 写入 `plan_review_max_rounds: 8` /
`impl_fix_max_rounds: 8` 覆盖默认的 3 轮。

同轮评审的另两条问题(不需改方案,归入下一实现轮修复):

- **R-02 [blocker]**:TC-03/TC-06 的 A 档证据文件里缺执行命令与显式退出码
  (当时命令行与 `EXIT=` 留在终端、没进日志文件)。本方案在 3.3 补上
  **证据留存格式**的硬要求。
- **R-03 [major]**:原"使用形态"正则不匹配 markdown 反引号里的变量名,
  导致 `deploy/kubernetes/agent/README.md` 报"基线旧名=0、现新名=0",
  该文件的改名实际**未被任何断言保护**。3.1 新增逐文件**旧名→新名映射
  断言**修掉这个盲区。

## 背景与目标

用户部署时发现 `REDIS_PASSWORD` 没有 `DOPILOT_` 前缀。全仓扫描后确认这不是
孤例,共 **4 个**面向部署的环境变量违反命名约定,而
`docs/architecture/04-configuration.md:12` 已把"常规部署用 `DOPILOT_*`
环境变量覆盖"写成架构事实——即当前实现与已记录的约定不一致。

无前缀的通用名在部署环境里有真实碰撞风险:`REDIS_PASSWORD` / `REDIS_HOST` /
`AGENT_ID` 都是极常见的名字,同宿主机上其他服务(或 K8s 同 Pod 的 sidecar、
CI runner 的既有环境)一旦已定义同名变量,会被静默继承进 dopilot 容器,
从而串改 Redis 连接串或 agent 身份。

目标:把这 4 个变量全部改为 `DOPILOT_` 前缀,使"所有 dopilot 部署环境变量
均以 `DOPILOT_` 开头"成为无例外的规则,并在 docs 落为持久约定。

### 扫描结果(全仓,含代码/compose/K8s/CI/脚本/文档)

需要修正(部署面):

| 现名 | 改为 | 消费方 |
|---|---|---|
| `REDIS_PASSWORD` | `DOPILOT_REDIS_PASSWORD` | 三份 compose 的变量替换(拼 `DOPILOT_REDIS_URL` + redis `--requirepass`)、README ×2 |
| `REDIS_HOST` | `DOPILOT_REDIS_HOST` | `docker-compose.agent.yml` 的 Redis URL 构造、README ×2 |
| `AGENT_ID` | `DOPILOT_AGENT_ID` | agent 配置加载器 env 覆盖、`docker-compose.yml`(3 个 agent)、`docker-compose.agent.yml`、K8s StatefulSet(fieldRef pod 名) |
| `AGENT_WORKDIR` | `DOPILOT_AGENT_WORKDIR` | agent 配置加载器 env 覆盖、Dockerfile `ENV`、`docker-compose.yml`(3 个 agent)、`docker-compose.agent.yml`、K8s StatefulSet |

确认**不改**(经核实不属于本项目部署环境变量,或前缀由外部框架规定):

- `NEXT_PUBLIC_API_BASE`(`apps/web`):Next.js 强制以 `NEXT_PUBLIC_` 开头,
  改名即失效。
- CI 专用:`DOCKER_PLATFORMS`、`DOCKERHUB_USERNAME`、`DISPATCH_TOKEN`、
  `IMAGE`、`GITHUB_*`(`.github/workflows/docker.yml`)——GitHub Actions
  作用域内的 workflow env / secrets,不进产物容器。
- 测试专用:`E2E_BASE_URL`、`E2E_ADMIN_USER`、`E2E_ADMIN_PASS`
  (`apps/web/playwright.config.ts`、`e2e/helpers/ui.ts`)、`CI`。
- shell 局部变量:`scripts/smoke-*.sh` 里的 `ADMIN_USER`/`ADMIN_PASS`/
  `VERSION`/`AGENT_IDS` 等——脚本内赋值的局部量,非环境入参。
- agent 测试中的模块级常量 `AGENT_ID = "agent-x"`
  (`test_command_consumer.py:32`、`test_event_outbox.py:23`、
  `test_log_publisher.py:13`、`test_python_wheel.py:56`)——普通 Python 常量,
  与环境变量无关。
- `.ai/` 历史轮次文件(含 `2026-07-24/*/evidence/*.sh`):按硬规则只增不改。

## 改动范围

预计触及 **13 个文件**(> 10,故本方案先过 plan 阶段 Codex 评审):

| 文件 | 改动 |
|---|---|
| `apps/agent/dopilot_agent/config/loader.py` | env 覆盖读取 `DOPILOT_AGENT_ID` / `DOPILOT_AGENT_WORKDIR`(替换 `AGENT_ID` / `AGENT_WORKDIR`),同步 docstring;补注 `DOPILOT_AGENT_ID` 与 protocol runtime context 同名的口径(见实现方案 1.2) |
| `apps/agent/tests/test_config.py` | 现有用例改用新名;新增一条断言旧名已失效 |
| `apps/agent/tests/test_healthcheck.py` | `_use_config()` 的环境隔离元组(`:32`)改清理新名,否则宿主机若已设常规部署变量会覆盖测试 TOML;新增锚点用例 `test_use_config_isolates_deployment_env_overrides` 断言**配置加载阶段**在污染下仍抛 `ConfigError`(TC-08 的判别锚点,见 TC-08 行的说明) |
| `apps/agent/tests/test_python_wheel.py` | 新增两条用例:①agent 进程环境里存在冲突的 `DOPILOT_AGENT_ID` 时,子进程仍取 runtime context 的值(守住 1.2 的同名裁定);②对照用例——不带 runtime context 时子进程读到继承值,证明①非平凡通过 |
| `deploy/docker/Dockerfile` | `ENV AGENT_WORKDIR=/agent-data` → `ENV DOPILOT_AGENT_WORKDIR=/agent-data`;第 119 行注释里的 `AGENT_ID` 同步 |
| `deploy/docker/docker-compose.yml` | 3 个 agent 的 `AGENT_ID`/`AGENT_WORKDIR`、6 处 `${REDIS_PASSWORD:-…}`、顶部 env 说明 |
| `deploy/docker/docker-compose.server.yml` | `${REDIS_PASSWORD:-…}` 各处、顶部 env 说明 |
| `deploy/docker/docker-compose.agent.yml` | `AGENT_ID`/`AGENT_WORKDIR`、`${REDIS_PASSWORD:?…}`/`${REDIS_HOST:-…}`、顶部必填/可选 env 说明与 Deploy 示例 |
| `deploy/kubernetes/agent/statefulset.yaml` | `AGENT_ID`(fieldRef)/`AGENT_WORKDIR` 两个 env 名 |
| `deploy/kubernetes/agent/README.md` | 第 17 行 `AGENT_ID` 表述 |
| `README.md` | Quick deploy `.env` 样例、agent 接入命令行 |
| `README.zh-CN.md` | 同上 |
| `docs/architecture/04-configuration.md` | 把"部署环境变量一律 `DOPILOT_` 前缀(含 compose 变量替换层)"落为明确约定;补 agent 侧 `DOPILOT_AGENT_ID`/`DOPILOT_AGENT_WORKDIR`、部署侧 `DOPILOT_REDIS_PASSWORD`/`DOPILOT_REDIS_HOST`;记录 1.2 的同名口径与混合升级警告 |

明确不动:`configs/*.toml`(TOML 字段名不是环境变量,`agent_id`/`workdir`
保持原样)、`packages/protocol`(runtime context 键名已合规,见 1.2)、
`apps/server`、`apps/web`、`scripts/`、`.github/workflows/`、`.ai/` 历史文件。

## 实现方案

### 1. 命名裁定

#### 1.1 硬改名,不保留旧名兜底

项目版本 `0.0.0`、无发布 tag(`git tag` 仅有 `backup/pre-normalize`),
处于发布前阶段;保留 `AGENT_ID` 回退分支只会留下需要长期维护的死代码,
且无法覆盖真正危险的混合升级场景(见风险节)。因此一次改净,提交信息按
Conventional Commits 标 `BREAKING CHANGE:`,升级动作只有两步:改 `.env`
里的变量名 + `docker compose pull`。

#### 1.2 `DOPILOT_AGENT_ID` 与 protocol runtime context 同名——刻意复用,不另起名

`DOPILOT_AGENT_ID` **已经存在**:
`packages/protocol/dopilot_protocol/execution.py:13` 把它作为
`DopilotRuntimeContext.agent_id` 的载体键,注入用户工作负载
(scrapy settings 与 python-wheel 子进程环境)。本方案把 agent 侧的配置覆盖
env 也命名为 `DOPILOT_AGENT_ID`,是**刻意复用同一名字表达同一事实**
("本 agent 的 id"),不另起 `DOPILOT_AGENT_SELF_ID` 之类的别名。依据:

- **值必然一致**:runtime context 的 `agent_id` 是被派发到的 agent 的 id,
  而 agent 只消费寻址到自己 id 的 Redis 命令流(`command_stream(agent_id)`),
  故二者由构造保证相等,不存在"两个不同的 agent id"。
- **子进程侧不受影响**:`apps/agent/dopilot_agent/runners/python_wheel.py:177`
  以 `dict(os.environ)` 起底,随后 operator `env` 覆盖、**runtime context 最后
  覆盖**(`:191` 注释即"Dopilot-owned context wins")。因此即使 agent 进程环境
  带入 `DOPILOT_AGENT_ID`,子进程拿到的仍是 runtime context 的值。既有用例
  `test_python_wheel.py:248 test_wheel_run_injects_runtime_context_env_last`
  已守住 operator `env` 方向,本方案补一条守住"继承进程环境"方向(TC-09)。
- 无需改动 `packages/protocol`,也没有需要同步的环境变量过滤名单
  (runner 不做 allow/deny list)。

### 2. 逐层落地

- **agent 加载器**:`os.environ.get("AGENT_ID")` → `"DOPILOT_AGENT_ID"`,
  `"AGENT_WORKDIR"` → `"DOPILOT_AGENT_WORKDIR"`;docstring 第 59 行的
  env → 字段映射表同步改名。TOML 字段名与优先级(env > TOML)不变。
- **Dockerfile**:烤进镜像的 `ENV AGENT_WORKDIR=/agent-data` 改名。这行与
  加载器必须同批改——否则新代码读不到 workdir env,会静默回落到
  `configs/agent.toml` 的 `workdir = "/agent-data"`(值恰好相同,不会立刻
  出错,但等于悄悄失去 env 通道),故本次两处一起改并由 TC-04 交叉验证。
- **compose ×3**:变量替换名改前缀,`:-` 默认值与 `:?` 快速失败语义
  逐字保留(`${DOPILOT_REDIS_PASSWORD:?set DOPILOT_REDIS_PASSWORD or
  DOPILOT_REDIS_URL}`),顶部 env 文档块与 Deploy 示例同步。
- **K8s StatefulSet**:两个 env 名改前缀,`fieldRef: metadata.name` 的取值
  方式不变(每 Pod 唯一 id 的机制保持)。
- **agent 测试**:`test_config.py` 全量改新名并补反向用例;
  `test_healthcheck.py:32` 的隔离元组改新名(第 02 轮 plan 评审 R-01);
  `test_python_wheel.py` 补 1.2 的同名守护用例。
- **README ×2 / K8s README / 架构文档**:同步所有出现处。

### 3. 收口检查(两个可判定脚本 + 证据留存格式)

静态收口不写成表格里的一行命令(第 01 轮 plan 评审 R-01:markdown 表格中
为规避管道符写的 `\|` 在 ERE 里是字面量,命令会静默失效),改为随任务落盘
两个脚本,`bash` 直接跑、**退出码 0 = 通过**,并把完整输出留作证据。

#### 3.1 `evidence/tc03-legacy-name-scan.sh`(TC-03)

**契约(本次修订的核心,对应实现层评审 R-01 / R-03)**

本方案自身要求 README ×2、三份 compose、K8s 清单、架构文档、加载器注释写出
**"旧名已废弃、请改名"的升级提示**,而这类提示**必须点名旧变量**才对用户有
用(他要照着改 `.env`)。因此"旧名文本零出现"是与本方案其他要求互斥的、
不可达的契约,初版 TC-03 写错了。修订后的契约把"**实际使用**"与"**受控的
废弃说明**"分开判定,共 **5 组断言**,全部由脚本判定、退出码 0 = 通过:

| 组 | 断言 | 挡住什么 |
|---|---|---|
| ① | 正则自检:`ANY_OLD` 只命中裸旧名(不误伤 `DOPILOT_AGENT_ID`、`AGENT_IDS`);`USE_OLD` 对 **6 种使用形态**各命中一条正样本、对散文/反引号/新名不命中 | 正则本身失效导致后面全部假通过(第 01 轮 plan 评审 R-01 的原始教训) |
| ② | **使用形态**残留必须为 0 | 漏改任何一处真正被消费的变量 |
| ③ | **逐文件旧名→新名映射断言**(修 R-03):对每个受影响文件、每个在 `git show HEAD:<file>` 中出现过的旧名(**任意形态,含 markdown 反引号**),工作区必须出现 ≥1 次对应的 `DOPILOT_` 前缀名 | 文件保持旧名、或把变量整段删掉,都会 FAIL。这正是 R-03 指出的盲区:`deploy/kubernetes/agent/README.md` 的旧名写在反引号里,不属使用形态,旧版脚本对它报"基线 0 / 现新名 0",三种情况都能通过 |
| ④ | **废弃说明预算**:每个文件残留的裸旧名出现次数 ≤ 该文件声明的提示预算;预算外文件出现裸旧名即 FAIL,且清单逐行打印供复核 | 新增未经声明的裸旧名(无论是漏改还是随手写的注释)悄悄溜进来 |
| ⑤ | agent 测试目录含旧名的文件集合与允许清单**集合相等** | `test_healthcheck.py` 那类"用元组/循环操作环境变量、躲过按名 grep"的漏改(第 02 轮 plan 评审 R-01) |

**使用形态**(6 种,`USE_OLD`):变量替换 `${X}` / `$X`、YAML 映射键 `X:`、
K8s `- name: X`、env 赋值 `X=`、引号字符串字面量 `"X"`(env 名实参)、
Dockerfile `ENV X`。**不算**使用形态因而归入第 ③/④ 组判定的:markdown
反引号 `` `X` ``、自然语言散文、代码注释。

**正则**用真正的 ERE 分支 `\b(AGENT_ID|AGENT_WORKDIR|REDIS_PASSWORD|REDIS_HOST)\b`。
两处 `\b` 是关键,已在本机实测成立(GNU grep 的词构成字符含下划线):

- 不会命中 `DOPILOT_AGENT_ID`——`_` 与 `A` 均为词字符,其间无词边界;
- 不会命中 shell 数组 `AGENT_IDS`(`scripts/smoke-*.sh`)——`D` 与 `S` 之间同理。

**扫描范围**(受影响的部署面 + 文档):`deploy/`、`configs/`、`docs/`、
`scripts/`、`examples/`、`README.md`、`README.zh-CN.md`、
`apps/agent/dopilot_agent/`、`apps/server/dopilot_server/`、`packages/`、
`.github/workflows/`。

范围排除项与理由:

- `.ai/`——过程痕迹,硬规则只增不改(含 `2026-07-24/*/evidence/*.sh`);
- `apps/*/tests/`——**不做整目录零残留断言**,因为 4 个文件里 `AGENT_ID` 是
  普通模块常量、且 TC-02 的反向用例**必须**引用旧名;测试目录改为用第 ⑤ 组
  集合相等断言精确收口,行为正确性由 TC-01/TC-02/TC-07/TC-08 覆盖;
- `node_modules/`、`apps/web/.next/`、`.venv/`、`__pycache__/`——依赖与构建产物
  (`.pyc` 里含旧字符串,实测会误报)。

**声明的废弃说明预算**(第 ④ 组用;数字是该文件允许残留的裸旧名**出现次数**
上限,写少了不算失败、写多了必须回到本方案改预算并重评):

| 文件 | 预算 | 用途 |
|---|---|---|
| `README.md` | 4 | 升级段落列出 4 个旧名 |
| `README.zh-CN.md` | 4 | 同上(中文) |
| `deploy/docker/docker-compose.agent.yml` | 4 | 顶部升级警告列出 4 个旧名 |
| `deploy/docker/docker-compose.yml` | 2 | 顶部 env 说明举例 2 个 |
| `deploy/docker/docker-compose.server.yml` | 1 | 顶部 env 说明举例 1 个 |
| `deploy/kubernetes/agent/statefulset.yaml` | 2 | env 块注释说明 2 个旧键已废弃 |
| `docs/architecture/04-configuration.md` | 2 | 命名约定小节举例 2 个 |
| `apps/agent/dopilot_agent/config/loader.py` | 2 | 加载器注释说明 2 个旧名无兜底 |
| 其他任何文件 | 0 | — |

#### 3.2 `evidence/tc06-k8s-env-check.sh`(TC-06)

环境无 kubectl,故以可判定脚本对 StatefulSet 同时断言**新键存在**、
**`fieldRef` 关联未丢**、**旧键缺席**,并附**反向自检**(把新键改回旧名的
临时副本必须被判失败,证明断言非恒真)。

#### 3.3 A 档证据留存格式(硬要求,对应实现层评审 R-02)

每条 A 档用例的证据文件**自身**必须完整可复核,不依赖终端上下文:

1. 首行起写出**完整执行命令**(含为绕过本机 `.venv` 路径问题而设的
   `PYTHONPATH` 等前置环境变量);
2. 完整 stdout **与** stderr(`2>&1` 合流);
3. **末行显式写出退出码**(`EXIT=<n>`),且必须与实现记录里报告的值一致。

即证据文件须由 `{ echo '$ <cmd>'; <cmd> 2>&1; echo "EXIT=$?"; } > <log>` 之类
的形式生成;**不得**只把脚本 stdout 重定向进文件(第 01 轮 R-02 正是如此:
命令行与 `EXIT=` 留在了终端)。

两个脚本的具体实现随实现轮落盘到 `evidence/`;其头部注释须写明本节契约的
组别编号,便于评审按组核验。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 改完 agent 加载器与测试 | `python -m pytest apps/agent/tests/test_config.py -v` | 全绿;`DOPILOT_AGENT_ID`/`DOPILOT_AGENT_WORKDIR` 覆盖 TOML 的用例通过 | 命令 + 完整 stdout/stderr + 退出码 → `evidence/tc01-agent-config-pytest.log` |
| TC-02 | A | 新增用例:仅设旧名 `AGENT_ID=legacy-id`、`AGENT_WORKDIR=/legacy`,不设新名 | 同上 pytest 运行该用例 | 旧名**不生效**:`agent_id`/`workdir` 取 TOML 值(非 `legacy-id`/`/legacy`)——确认改名彻底、无隐式兜底(非 happy-path) | 同 TC-01 日志 |
| TC-03 | A | 全部文件改完;脚本按 3.1 契约落盘(正则与预算表见 3.1,不在表格内写正则) | `bash .ai/2026-07-28/unify-env-var-prefix/evidence/tc03-legacy-name-scan.sh` | 脚本**退出码 0** 且末行 `RESULT: PASS`,3.1 表中 **5 组断言全部通过**:①正则自检(含 6 种使用形态各一条正样本、散文/反引号/新名不误伤);②使用形态残留 0 处;③逐文件旧名→新名**映射断言**——含 markdown 反引号形态,`deploy/kubernetes/agent/README.md` 必须被真正覆盖(R-03);④各文件裸旧名出现次数 ≤ 3.1 声明的废弃说明预算、预算外文件为 0,清单逐行打印;⑤agent 测试目录集合相等 + `test_healthcheck` 隔离元组已改新名 | 按 3.3 格式:命令 + 完整 stdout/stderr + 末行 `EXIT=<n>` → `evidence/tc03-legacy-name-scan.log` |
| TC-04 | A | docker compose 可用(v5.1.4 已确认);不启容器 | 分别对三份 compose 跑 `docker compose -f <file> config`,并注入新名(agent 栈补 `DOPILOT_AGENT_TOKEN`/`DOPILOT_SERVER_URL`) | 三份均解析成功(退出码 0);渲染结果中 `DOPILOT_REDIS_URL` 含注入的密码、agent 服务含 `DOPILOT_AGENT_ID`/`DOPILOT_AGENT_WORKDIR`,且**不含**任何旧名 key | 命令 + 完整渲染输出 + 退出码 → `evidence/tc04-compose-config.log` |
| TC-05 | A | 同 TC-04 环境,`env -u` 清掉 `DOPILOT_REDIS_PASSWORD` 与 `DOPILOT_REDIS_URL` | `docker compose -f docker-compose.agent.yml config` | 退出码非 0,错误信息点名 `DOPILOT_REDIS_PASSWORD`(证明 `:?` 快速失败语义随改名保留,非 happy-path) | 命令 + 完整 stderr + 退出码 → `evidence/tc05-compose-failfast.log` |
| TC-06 | A | K8s 清单改完(环境无 kubectl,用静态断言);脚本按 3.2 落盘 | `bash .ai/2026-07-28/unify-env-var-prefix/evidence/tc06-k8s-env-check.sh` | 脚本**退出码 0** 且末行 `RESULT: PASS`:两个新键均存在、`DOPILOT_AGENT_ID` 仍由 `fieldRef: metadata.name` 取值、`DOPILOT_AGENT_WORKDIR` 值仍为 `/agent-data`、无裸旧键;**反向自检**证明裸旧键断言非恒真 | 按 3.3 格式:命令 + 完整 stdout/stderr + 末行 `EXIT=<n>` → `evidence/tc06-k8s-env-check.log` |
| TC-07 | A | 全部改完 | `ruff check apps packages` + `python -m pytest apps/agent packages/protocol` | 均通过,退出码 0(改名未破坏 agent 其他行为) | 命令 + 完整输出 + 退出码 → `evidence/tc07-lint-and-tests.log` |
| TC-08 | A | 同 TC-07,但**故意污染**环境;并在 `test_healthcheck.py` 新增锚点用例 `test_use_config_isolates_deployment_env_overrides` | `DOPILOT_AGENT_ID=polluted DOPILOT_AGENT_WORKDIR=/polluted DOPILOT_REDIS_PASSWORD=polluted python -m pytest apps/agent` | 全绿,证明所有 agent 测试对新名做了环境隔离。判别锚点是新增用例断言的**配置加载阶段**(污染下加载缺 `agent_id` 的 TOML 必须抛 `ConfigError`)——**不能**用 `test_healthcheck_fails_on_bad_config` 作锚点:实测隔离失效时它仍返回 1(配置被污染补全后,紧随的 scrapyd 探针照样失败),退出码掩盖了隔离已失效。非 happy-path,对应第 02 轮 plan 评审 R-01 | 按 3.3 格式 → `evidence/tc08-polluted-env-pytest.log` |
| TC-08b | A | 同上;临时副本上把隔离元组回退为旧名,跑完无条件还原 | `bash .ai/2026-07-28/unify-env-var-prefix/evidence/tc08-reverse-selfcheck.sh` | 退出码 0、`RESULT: PASS`:回退副本上锚点用例**必须失败**(`DID NOT RAISE ConfigError`),证明 TC-08 有判别力而非恒真;且脚本以运行前后 sha256 比对断言工作区已还原 | 按 3.3 格式 → `evidence/tc08-reverse-selfcheck.log` |
| TC-09 | A | 新增 `test_python_wheel.py` 用例:agent 进程环境设 `DOPILOT_AGENT_ID=inherited-wrong`,派发带 runtime context 的 wheel 任务 | 运行该用例并检查子进程实际读到的值 | 子进程取 **runtime context** 的 agent id,而非继承自 agent 进程环境的 `inherited-wrong`(守住 1.2 的同名复用裁定,非 happy-path) | 按 3.3 格式 → `evidence/tc09-runtime-context-precedence.log` |
| TC-09b | A | 新增对照用例:同样污染 agent 进程环境,但派发**不带** runtime context 的任务 | 同上 | 子进程读到继承值 `inherited-wrong`——证明该环境变量确实到达子进程,故 TC-09 检验的是**覆盖优先级**而非平凡通过 | 同 TC-09 日志 |

C 档 0 条(11 条全部可由非交互命令判定)。所有 A 档证据须满足 3.3 的留存格式
(命令 + 完整 stdout/stderr + 末行 `EXIT=<n>`)。

## 风险与回滚

- **破坏性变更**:沿用旧变量名的现网部署升级后,旧名被忽略。影响面明确:
  `.env` / K8s manifest 里 4 个名字加前缀即可。提交标 `BREAKING CHANGE:`,
  README 与架构文档同批更新。
- **混合升级的静默故障(最需要提醒用户的一点)**:若只更新 compose/manifest
  而**不拉新镜像**,旧镜像里的旧代码读不到新名,`agent_id` 会静默回落到
  烤进镜像的 `configs/agent.toml` 的 `scrapy-agent-1`——一体栈三个 agent
  会共用同一 id,症状隐蔽(节点列表少节点、命令分配错乱)且探针不报错。
  这一点无法从新代码侧兜底(旧代码在旧镜像里),只能靠文档强约束:
  升级 compose 必须同时 `docker compose pull`。会在 README 升级说明与
  `docs/architecture/04-configuration.md` 写明。
- **`DOPILOT_AGENT_ID` 同名**:与 protocol runtime context 键复用同一名字。
  已核实值必然一致且子进程侧 runtime context 最后覆盖(1.2),并由 TC-09
  专项守护;若将来两者语义真的分叉,须走新增决策记录再拆名。
- **`--requirepass` 与 URL 不同步**:`REDIS_PASSWORD` 在同一份 compose 里
  同时喂 redis 服务的 `--requirepass` 和 server/agent 的 `DOPILOT_REDIS_URL`,
  漏改任一处会导致 AUTH 失败。由 TC-03(零残留 + 基线不减)与 TC-04
  (渲染后密码一致)双重兜住。
- **回滚**:纯改名 + 文档 + 测试,无数据迁移、无 schema 变更;`git revert`
  单个提交即可完全回退,回退后旧 `.env` 继续可用。
