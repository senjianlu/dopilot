# 00 · 阶段 1 实现任务书（Scrapy 跑稳）

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield，按 `apps/` + `packages/` 自有结构实现。阶段 1 仍不 import `reference/scrapydweb`，不把 `reference/` 放进 Docker build context。
>
> 本文是阶段 1 的工程执行任务书。开发与初测交由 Claude 完成；Codex 拿到代码后负责 review、复跑关键测试、执行集成验收，并把问题写入本阶段 review 文档。

---

## 0. 阶段 1 目标

阶段 1 的目标是把 **Scrapy 执行链路跑稳**，第一次形成真实执行闭环：

```text
web/server API
  -> server ScrapydExecutor
  -> dopilot-agent HTTP API
  -> agent 内管本机 scrapyd
  -> scrapy job
  -> agent tail job.log
  -> server pull 日志增量
  -> /server-data/logs 正文 + PostgreSQL 索引/offset/status
  -> server->web SSE
```

阶段 1 完成后，用户应能：

- 上传或引用一个已构建 Scrapy egg。
- 把 egg 经 server 转发到 agent，由 agent 调本机 scrapyd `/addversion.json`。
- 立即运行一个 spider，由 server 生成 `execution_id` / `attempt_id` 并下发 agent。
- 在数据库中看到 execution / attempt / log index 状态。
- 通过 server 日志 API/SSE 看到 job.log 增量。
- 任务结束后完成 final drain，日志正文留在 `/server-data/logs`，索引状态变为 complete。
- 容器重启后，正在运行/已结束但未 final drain 的任务能进入明确状态，不出现“永远 running 且无解释”的任务。

阶段 1 的关键词是 **真实 Scrapy、真实日志、真实状态机、真实重启语义**。不要同时引入 Python 脚本执行器或 Docker 长连接执行器。

---

## 1. 明确不做

阶段 1 不实现以下内容：

- 不实现 Python 脚本执行器。
- 不实现 Docker 长连接执行器。
- 不做源码/Git/CI 构建 egg；第一版只支持已构建 egg 上传/转发。
- 不让 server 直连裸 scrapyd；server 只连 dopilot-agent。
- 不让 server 直连节点 Docker daemon。
- 不使用 WebSocket。
- 不让 agent 主动推日志或主动回调 server。
- 不做多 server 副本、分布式锁、多 worker uvicorn。
- 不做多用户/RBAC。
- 不做复杂前端工作流；前端只交付阶段 1 验证 Scrapy 链路需要的最小页面。

---

## 2. 架构约束

### 2.1 节点形态

阶段 1 的节点是 **dopilot-agent**，不是裸 scrapyd。

- agent 对外端口：`6800`，只暴露 agent HTTP API。
- scrapyd 由 agent 子进程拉起，只监听容器内部端口，例如 `6801`。
- compose 中 server 访问 `agent:6800`。
- scrapyd 内部端口不要映射到宿主机作为正式链路。

### 2.2 日志主线

第一版只使用 server pull：

- agent 提供 `GET /logs/tail`，按 offset 返回增量。
- server 按 offset 拉取 agent 日志，offset 权威在 PostgreSQL。
- server 写日志正文到 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.log`。
- PostgreSQL 只存索引、offset、状态，不存日志正文。
- server 通过 SSE 推给 web。

### 2.3 结束检测

server 轮询 agent `GET /status` 判定状态：

- `running`
- `finished`
- `failed`
- `canceled`
- `unknown`

任务结束后：

```text
running -> finalizing -> final drain -> complete
```

final drain 受两个配置约束：

- `eof_stable_seconds`
- `final_drain_hard_timeout_seconds`

complete 后 server 调 agent cleanup API。agent 也可以有 TTL 兜底，但不得早于 server final drain 删除 job.log。

---

## 3. 数据库与迁移

阶段 1 必须新增 Alembic revision，不允许用 `Base.metadata.create_all()` 代替正式迁移。

至少新增这些表或等价模型：

### 3.1 executions

- `id`
- `task_type`: phase 1 只实际支持 `scrapy`
- `target`
- `node_strategy`: `all` / `random` / `selected`
- `status`: `queued` / `running` / `finalizing` / `complete` / `failed` / `canceled` / `lost`
- `params` JSONB
- `created_at`
- `started_at`
- `finished_at`

### 3.2 execution_attempts

- `id`
- `execution_id`
- `agent_id`
- `node_id` 或稳定 node 外键
- `remote_job_id`，对应 scrapyd job id
- `status`
- `started_at`
- `finished_at`
- `exit_code` 可为空
- `error_code` / `error_detail` 可为空

### 3.3 execution_log_files

主键建议为 `(execution_id, attempt_id, stream)`。

- `execution_id`
- `attempt_id`
- `stream`: phase 1 使用 `log`
- `storage_path`
- `size_bytes`
- `last_pulled_offset`
- `final_offset`
- `status`: `active` / `finalizing` / `complete` / `missing` / `expired`
- `started_at`
- `finished_at`
- `retained_until`

### 3.4 scrapy_artifacts 或部署记录

用于记录已上传 egg 与版本：

- `id`
- `project`
- `version`
- `filename`
- `sha256`
- `size_bytes`
- `created_at`

也可以先用 execution params 记录 project/version，但必须清楚说明 phase 1 如何定位已部署 egg。

---

## 4. Agent 要求

### 4.1 agent 启动本机 scrapyd

agent 启动时负责拉起本机 scrapyd 子进程。

要求：

- 使用 glibc 基础镜像，不用 Alpine。
- compose 保持 `init: true`。
- scrapyd 工作目录在 `/agent-data` 下。
- agent 退出时正确终止 scrapyd 子进程。
- agent 重启后能基于 `/agent-data/state/executions/{attempt_id}.json` 恢复映射。

### 4.2 agent API

阶段 1 必须把 phase 0 的 501 stub 替换为真实行为。

| Endpoint | 行为 |
|---|---|
| `POST /run` | 运行 Scrapy job。输入包含 `execution_id`、`attempt_id`、project/version/spider/settings/args。agent 调本机 scrapyd `/schedule.json`，持久化 attempt 映射，返回 remote job id。 |
| `POST /stop` | 停止指定 attempt。agent 调本机 scrapyd cancel API；如果 job 已结束，返回幂等成功或明确状态。 |
| `GET /status` | 返回 attempt 当前状态，server 用它判断是否进入 finalizing。 |
| `GET /logs/tail` | 按 `execution_id`、`attempt_id`、`stream`、`offset`、`max_bytes` 返回日志增量。 |
| `POST /executions/{attempt_id}/logs/cleanup` | final drain 完成后删除或标记清理 agent 侧日志。 |
| `POST /artifacts/scrapy/egg` | 接收 egg 并调本机 scrapyd `/addversion.json`。 |
| `GET /health` | 继续返回 agent_id/capabilities/workdir；新增 scrapyd 子进程健康信息。 |

### 4.3 agent 状态文件

每个 attempt 写入：

```text
/agent-data/state/executions/{attempt_id}.json
```

至少包含：

- `execution_id`
- `attempt_id`
- `scrapyd_job_id`
- `project`
- `version`
- `spider`
- `log_path`
- `created_at`
- `updated_at`

状态文件必须原子写入，避免容器崩溃留下半截 JSON。

---

## 5. Server 要求

### 5.1 ScrapydExecutor

`apps/server/dopilot_server/executors/scrapyd.py` 从 501 stub 变为真实实现：

- 选择目标节点。
- 生成 execution / attempt。
- 调 agent `/run`。
- 持久化 remote job id。
- 初始化 `execution_log_files`。
- 返回 execution id 和初始状态。

### 5.2 节点策略

阶段 1 至少支持：

- `all`
- `random`
- `selected`

要求：

- 只选择 `healthy` agent。
- `random` 在健康节点中选一个。
- `selected` 使用稳定 `agent_id` 或 node id，不使用顺序索引。
- 没有可用节点时返回结构化错误，不创建半成品 running execution。

### 5.3 日志 pull loop

server 实现日志 pull loop：

- 后台低频 drain active execution。
- Web 打开日志窗口时升到实时频率。
- 多个窗口看同一 execution 不应启动多个重复 pull loop。
- 按 `last_pulled_offset` 幂等拉取。
- 每次最多拉 `max_tail_bytes_per_pull`。
- 写文件和更新 DB offset 必须顺序一致，避免 DB offset 先前进但文件没写成功。

### 5.4 SSE

server 提供 web 可用的 SSE：

- `GET /api/v1/executions/{execution_id}/logs/stream`
- 发送增量日志事件。
- 支持 `Last-Event-ID` 或等价重连补洞机制。
- Web 认证开启时必须校验访问权限。若采用短期 stream token，文档和测试必须覆盖 token 签发/过期。

### 5.5 API

阶段 1 至少提供：

| Endpoint | 行为 |
|---|---|
| `POST /api/v1/artifacts/scrapy/egg` | 上传 egg，server 转发到指定或默认 agent 部署。 |
| `POST /api/v1/executions/run` | 真实运行 Scrapy。 |
| `GET /api/v1/executions/{id}` | 返回 execution、attempt、节点、状态。 |
| `GET /api/v1/executions/{id}/logs` | 返回已落地日志片段或 tail 快照。 |
| `GET /api/v1/executions/{id}/logs/stream` | SSE 实时日志。 |
| `POST /api/v1/executions/{id}/cancel` | 停止任务。 |
| `GET /api/v1/nodes` / `POST /api/v1/nodes/refresh` | 延续 phase 0，健康信息包含 agent/scrapyd 状态。 |

---

## 6. Web 要求

阶段 1 前端只做最小可验收页面，不做完整运营后台。

至少包含：

- 节点页：显示 agent health 和 scrapyd health。
- Scrapy 运行页：选择 project/version/spider，填写 args/settings，选择节点策略，点击运行。
- Executions 列表：显示状态、agent、开始/结束时间。
- Execution 详情页：显示状态、attempt、remote job id。
- 日志 viewer：通过 SSE 或轮询显示实时 job.log。
- 取消按钮：调用 cancel API。

前端必须保持中文默认文案，并补齐英文 key。

---

## 7. 测试要求

你说得对，阶段 1 的测试内容会非常多。原因是阶段 1 同时引入：

- 子进程生命周期。
- 外部 HTTP 服务 scrapyd。
- server-agent 协议。
- PostgreSQL 状态机。
- 文件日志与 DB offset 一致性。
- SSE 实时流。
- 容器重启和任务丢失语义。

因此阶段 1 的测试必须分层，不能只靠一次手动 compose 验证。

### 7.1 Unit tests

必须覆盖：

- config loader 新增 scrapyd/agent 配置。
- agent state file 原子写入/读取/损坏文件处理。
- agent auth。
- agent run/status/tail/cleanup 的参数校验。
- server node selection：all/random/selected/no healthy nodes。
- server execution 状态迁移合法性。
- log offset 计算：空文件、追加、offset 超过文件、文件丢失、max_bytes 截断。
- LogSource 抽象。
- ErrorResponse shape。

### 7.2 Contract tests

必须覆盖 server-agent 协议：

- `POST /run` request/response schema。
- `GET /status` response schema。
- `GET /logs/tail` offset 语义。
- `POST /stop` 幂等语义。
- cleanup 后 tail 的返回语义。
- shared_token 开启/关闭两种模式。

建议把 schema 放在 `packages/protocol`，server 和 agent 都引用同一套模型。

### 7.3 Server integration tests

使用 mocked agent 覆盖：

- `/executions/run` 创建 execution/attempt/log index。
- agent `/run` 成功。
- agent `/run` 失败。
- 多节点 all 策略。
- random 策略可控。
- selected 策略。
- 没有健康节点。
- status 从 running 到 finished 后进入 finalizing/complete。
- final drain 写日志文件并推进 DB offset。
- cancel 调 agent `/stop`。

### 7.4 Agent integration tests

使用 fake scrapyd 或真实 scrapyd 二选一：

- addversion 成功/失败。
- schedule 成功返回 job id。
- status 查询 running/finished/unknown。
- tail job.log 按 offset 返回。
- cleanup 删除或标记日志。
- agent 重启后从 state 文件恢复 attempt 映射。

如果真实 scrapyd 在 CI 中不稳定，允许用 fake scrapyd 做自动化测试，但必须另有 compose smoke 覆盖真实 scrapyd。

### 7.5 Log/SSE tests

必须覆盖：

- SSE 建连后收到历史补齐。
- SSE 收到后续增量。
- 断线重连不重复或少发日志。
- 多客户端订阅同一 execution 不产生多个 pull loop。
- final drain 后 SSE 发送完成事件。
- stream token 或 auth 失败时拒绝连接。

### 7.6 Compose smoke tests

必须提供可重复命令，至少覆盖：

```bash
cd deploy/docker
docker compose down -v
docker compose up -d --build
```

随后验证：

- migrate 仍能从空库升级到 head。
- agent 启动 scrapyd 子进程。
- server `/nodes/refresh` 返回 healthy agent，且 scrapyd health 正常。
- 上传 demo egg 成功。
- 运行 demo spider 成功。
- 日志能从 agent tail 到 server 文件。
- SSE 或日志 API 能读到日志。
- execution 最终 complete。
- `docker compose down -v` 清理成功。

### 7.7 Restart/failure tests

阶段 1 必须定义并测试这些故障：

- agent 容器重启，scrapyd 子进程随之重启。
- agent 重启后，state 文件存在但 scrapyd job 不存在。
- job.log 存在但 status unknown。
- server 容器重启后，从 DB 恢复 active/finalizing execution。
- DB 可用但 agent 不可达。
- agent 可达但 scrapyd 不可达。
- job.log 被提前删除。
- tail offset 大于文件大小。

每个故障必须落到明确状态，例如 `lost`、`failed`、`missing`，不能无限 running。

### 7.8 Test command checklist

Claude 完成阶段 1 后必须运行并记录：

```bash
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
```

还必须运行阶段 1 的 compose smoke。若因环境限制无法运行真实 scrapyd compose smoke，必须明确写出：

- 哪条命令失败。
- 失败输出摘要。
- 是否是环境问题还是代码问题。
- Codex 需要如何复现。

---

## 8. Demo Scrapy 项目

阶段 1 需要一个最小 demo spider，用于自动化和 compose smoke。

要求：

- 放在 dopilot 自有测试/fixtures 目录，不能 import reference。
- spider 运行时间短。
- 输出确定性日志，例如固定几行 `phase1 demo spider started/done`。
- 可构建 egg。
- compose smoke 使用这个 egg。

可接受目录：

```text
apps/agent/tests/fixtures/scrapy_demo/
```

或：

```text
tests/fixtures/scrapy_demo/
```

如果构建 egg 的依赖太重，允许提交一个小型预构建测试 egg，但必须记录构建来源和 sha256。

---

## 9. Docker 要求

agent image 阶段 1 必须包含：

- dopilot-agent。
- scrapyd。
- Scrapy 运行所需依赖。
- 可写 `/agent-data`。

compose 保持：

- `db`
- `migrate`
- `agent`
- `server`

server 不包含 web SPA，不 copy `apps/web`。

agent 只暴露 `6800`。若为了调试临时暴露 scrapyd 内部端口，不能提交为默认 compose。

---

## 10. 验收标准

阶段 1 只有满足以下条件才算完成：

1. 所有 phase 0 测试继续通过。
2. 新增 phase 1 unit / contract / integration tests 通过。
3. Alembic migration 能从 phase 0 schema 升级到 phase 1 schema。
4. Clean-volume compose smoke 通过。
5. demo egg 上传成功。
6. demo spider 运行成功。
7. server 能记录 execution / attempt / log index。
8. agent 能 tail job.log。
9. server 能把日志正文写入 `/server-data/logs`。
10. SSE 或日志 API 能读取到日志。
11. execution 最终进入 complete/failed/canceled/lost 之一，不会卡死 running。
12. agent/server 重启场景有明确状态语义和测试覆盖。
13. 工作区无生成产物残留。
14. README 或阶段文档记录实际运行命令。

---

## 11. Codex review 顺序

Codex 拿到 Claude 的阶段 1 代码后按以下顺序 review：

1. 看 migration：是否无 `create_all` 正式路径，是否可从 phase 0 升级。
2. 看 server-agent protocol：schema 是否共享，错误 envelope 是否一致。
3. 看 agent 子进程：scrapyd 生命周期、端口、workdir、退出清理。
4. 看 execution 状态机：是否有非法状态跳转或永远 running。
5. 看日志链路：offset、文件写入、DB 更新顺序、final drain。
6. 看 SSE：鉴权、重连、多客户端、完成事件。
7. 看节点策略：只选 healthy agent，稳定 id，不用顺序索引。
8. 看 Docker：server 不含 web，agent 不暴露裸 scrapyd，compose clean-volume 可跑。
9. 跑测试清单。
10. 跑 clean-volume compose smoke。
11. 记录 review 到 `docs/phases/phase-1/01-review.md`。

---

## 12. 交付物

Claude 阶段 1 完成时至少应交付：

- server execution / attempt / log index 模型与 migration。
- shared protocol schemas。
- agent 内管 scrapyd。
- agent `/run` / `/stop` / `/status` / `/logs/tail` / cleanup / egg upload。
- server `ScrapydExecutor`。
- server 日志 pull loop。
- server SSE 或日志实时 API。
- 最小 web 页面。
- demo Scrapy fixture。
- 单元/契约/集成/compose smoke 测试。
- 阶段 1 review response 文档，记录 Claude 已跑过的命令和结果。
