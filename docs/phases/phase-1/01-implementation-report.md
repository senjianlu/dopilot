# 01 · 阶段 1 实现报告（Claude）

> 本文是 Claude 对 `00-brief.md` 的实现交付报告：记录**实际改了什么、跑了哪些命令、结果如何**，供 Codex review（Codex 的 review 写入 `02-review.md`，按 brief §11 顺序）。
>
> **scrapydweb 参考边界**：本阶段全程未 import `reference/scrapydweb`，未将 `reference/` 放入任何 Docker build context；所有 dopilot 代码均为 greenfield，按 `apps/`+`packages/` 自有结构实现。

## 0. 结论速览

阶段 1 把 **Scrapy 执行链路真正跑通**：

```
web/server API → server ScrapydExecutor → dopilot-agent /run → agent 内管 scrapyd
  → scrapy job → agent tail job.log → server 按 offset pull 增量
  → /server-data/logs 正文 + PostgreSQL execution_log_files 索引/offset/status
  → server→web SSE
```

实现按依赖顺序分层落地：共享 protocol → server 模型/迁移/配置/缝 → agent 内管 scrapyd → server 执行器/节点策略/日志 pull loop/SSE/API → web 最小页面 → demo egg → Docker/compose/smoke → 分层测试。

## 1. 交付物与落点

### 1.1 共享协议 `packages/protocol`

- 新增 `dopilot_protocol/agent.py`：server↔agent 执行控制 schema —
  `AttemptStatus`(pending/running/finished/failed/canceled/unknown)、
  `AgentRunRequest/Response`、`AgentStopRequest/Response`、`AgentStatusResponse`、
  `CleanupResponse`、`EggDeployResponse`。
- `execution.py`：`ExecutionRunRequest` 增补 scrapy `params` 契约文档（project/spider/version/settings/args），无破坏性改动。
- 既有 `TailRequest/TailResponse`、`LogStream`、`ErrorResponse`、`HealthResponse` 复用。
- 新增 `tests/test_agent_schemas.py`。

### 1.2 server `apps/server`

- **模型**（`models/execution.py`）：`executions` / `execution_attempts` /
  `execution_log_files`（主键 `(execution_id, attempt_id, stream)`）/ `scrapy_artifacts`；
  `models/node.py` 增 `health` JSONB 列（承载 agent 上报的 scrapyd 健康）。
  `execution_id`/`attempt_id` 用 32 位 uuid hex 字符串（与 wire、文件路径、DB 三处一致）。
- **迁移**（`migrations/versions/0002_executions.py`）：从 phase-0 `0001` 升级到 phase-1；
  4 张新表 + `nodes.health`。**无 `create_all` 正式路径**（仅测试用 SQLite create_all）。
- **配置**（`config/settings.py`）：`LogsSettings` 增 `status_poll_interval_seconds` /
  `unreachable_lost_seconds` / `first_screen_max_lines` / `first_screen_max_bytes`（均带默认值，旧 TOML 仍兼容）。
- **执行器缝**（`executors/base.py`）：`BaseExecutor.run(request, ctx)` 引入 `ExecutorContext`
  (session+settings+agent_client)，执行器无状态。`executors/scrapyd.py` 由 501 stub 变真实实现。
- **节点策略**（`nodes/service.py`）：`select_target_nodes`（仅 healthy + scrapy 能力，按 all/random/selected 归约，
  无可用节点抛结构化 409，**不先建半成品 running execution**）、`pick_deploy_node`、`refresh_nodes` 落 `health`。
- **agent 客户端**（`clients/agent.py`）：`AgentClient`（run/stop/status/tail/cleanup/deploy_egg），
  区分 `AgentUnreachableError`（可重试）/`AgentResponseError`（agent 返回错误 envelope）。
- **日志主线**（`logs/`）：
  - `files.py`：正文落盘 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.log`；
    server 文件 offset 空间 vs agent 字节 offset 分离；首屏 tail（末 N 行 / M 字节）。
  - `reconcile.py`：`drain_attempt`（按 offset 拉增量 → **先写文件再推进 DB offset** → SSE fan-out）、
    `finalize_attempt`（final drain 受 `eof_stable_seconds` / `final_drain_hard_timeout_seconds` 约束 → complete → 调 agent cleanup）、
    `mark_attempt_lost`、`cancel_execution`。
  - `loop.py`：单实例后台 reconcile loop（冷 30s / 开窗 1s drain、status 轮询、不可达超时→lost、周期 refresh 节点）；
    每 tick 用 sessionmaker 新开 session。
  - `sse.py`：进程内 `SubscriptionManager` fan-out（多窗复用一个 pull loop）。
  - `stream_token.py`：无状态短期 SSE 令牌（HMAC，绑定 execution_id + 过期）。
  - `source.py`：`AgentTailLogSource`（`LogSource` 缝的具体实现）。
- **API**（`api/v1/`）：`POST /executions/run`、`GET /executions`、`GET /executions/{id}`、
  `POST /executions/{id}/cancel`、`GET /executions/{id}/logs`、`GET /executions/{id}/logs/stream`(SSE)、
  `POST /executions/{id}/logs/stream-token`、`POST /artifacts/scrapy/egg`；`nodes` 视图增 `health`。
- **app 装配**（`app.py`）：lifespan 仅在生产路径建 agent httpx client + 启动 reconcile loop，关闭时停 loop/关 client/dispose engine；`SubscriptionManager` 建在 `create_app`（无 lifespan 的测试也可用）。

### 1.3 agent `apps/agent`

agent 内管本机 scrapyd 子进程，对外只暴露 6800 root API（scrapyd 仅监听容器内 6801）。
真实实现 `/run` `/stop` `/status` `/logs/tail` `/executions/{attempt_id}/logs/cleanup`
`/artifacts/scrapy/egg`，`/health` 增 `detail.scrapyd`。per-attempt 原子状态文件
`{workdir}/state/executions/{attempt_id}.json` 为重启恢复来源。单测用进程内 fake scrapyd（httpx MockTransport），不需真实 scrapyd 二进制。

### 1.4 web `apps/web`

最小验收页：Nodes（agent + scrapyd 健康）、Scrapy 运行页、Executions 列表、Execution 详情、
LogViewer（`EventSource` SSE，auth 开启时先换 stream-token）、取消按钮。中文默认 + 英文 key 补齐。

### 1.5 demo fixture / Docker

- `tests/fixtures/scrapy_demo/`：project `demo` / spider `phase1`，离线、确定性日志
  （`phase1 demo spider started` / `phase1 demo spider done`，`item_scraped_count==2`）；
  预构建 egg `eggs/demo_phase1.egg`（sha256 见 fixture README）。
- `Dockerfile.agent` 装 scrapy/scrapyd；compose 只发布 6800；agent/server healthcheck；
  `scripts/smoke-phase1.sh` clean-volume 端到端 smoke。

## 2. 测试命令清单与结果（brief §7.8）

所有命令在本机 `.venv`（Python 3.12.3）执行。

| 命令 | 结果 |
|---|---|
| `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests` | ✅ **179 passed**（server 88 / agent 75 / protocol 16） |
| `.venv/bin/ruff check apps packages` | ✅ All checks passed |
| `corepack pnpm --filter web test` | ✅ 7 passed（6 files） |
| `corepack pnpm --filter web build` | ✅ vue-tsc typecheck clean + vite build ok（仅既有 chunk>500kB 警告） |
| `cd deploy/docker && docker compose config` | ✅ 渲染通过；只发布 5000/6800/5432（无 6801） |

### 2.1 Alembic 迁移（真实 PostgreSQL，brief 验收 #3）

对 compose `db`（postgres:16）实测：

- 空库 → `alembic upgrade 0001`（phase-0）→ `alembic upgrade head`（0002，phase-1）成功；
  最终 7 张表（`alembic_version` + `auth_tokens` + `nodes` + `executions` + `execution_attempts` + `execution_log_files` + `scrapy_artifacts`），`nodes.health jsonb not null '{}'` 存在。
- 完整 `downgrade base` → 仅剩 `alembic_version` → 再 `upgrade head` 往返成功。

### 2.2 Compose smoke（brief §7.6 / 验收 #4–#11）

`bash scripts/smoke-phase1.sh`（clean volume：`down -v` → `up -d --build` → 等待 db/migrate/agent/server
→ 校验 agent `detail.scrapyd.running` → 登录 → `nodes/refresh` healthy → 上传 demo egg → 运行 demo spider
→ 轮询至终态 → 校验日志 marker → 断言 `complete` → `down -v`）。

**结果：✅ SMOKE PASSED（14/14）**，在本机（Docker 29.5.3 / Compose v5.1.4）实测：

```
PASS db healthy
PASS migrate completed (alembic upgrade head from empty -> head)
PASS agent healthy
PASS server healthy
PASS agent /health detail.scrapyd.running == true
PASS obtained admin bearer token
PASS nodes[0].status == healthy
PASS nodes[0].health.scrapyd.running == true
PASS committed egg present
PASS egg deployed (artifact.project == demo)
PASS execution created
---- terminal status: complete
PASS log marker present: 'phase1 demo spider started'
PASS log marker present: 'phase1 demo spider done'
PASS execution status == complete
passed: 14  failed: 0
```

即：真实 scrapyd 子进程拉起 → demo egg 上传部署 → demo spider 运行 → agent tail job.log →
server 按 offset pull 到 `/server-data/logs` → execution 最终 `complete`，全链路打通；`down -v` 清理成功。

## 3. 关键实现决策与不变量

- **offset 双空间**：agent 字节 offset（`last_pulled_offset`，权威用于下次 pull）与 server 文件 offset
  （`size_bytes`，用于 SSE event id / 快照读）分离——因为 agent 返回的是 utf-8 `replace` 解码后的文本，
  重新编码长度未必等于 agent 原始字节范围。
- **写序**：先写正文文件，再推进 DB offset（崩溃至多重复、绝不丢段，符合 brief §5.3）。
- **结束语义**：agent 终态 → finalizing → final drain（eof 稳定或硬超时）→ complete → 调 agent cleanup；
  持续不可达/unknown 超 `unreachable_lost_seconds` → `lost`。**不会无限 running**。
- **单实例**：单一 reconcile loop + 进程内 SSE fan-out；多窗复用一个 pull loop；uvicorn workers=1。
- **SSE 鉴权**：Web 认证开启时用短期 `stream_token`（HMAC、绑定 execution_id、TTL）；`EventSource` 无法带 header 故走 query。
- **节点策略**：仅 healthy + scrapy 能力；selected 用稳定 `agent_id`/node id；无可用节点先抛 409。

## 4. 对抗性自审与修复

实现完成后对 server 核心（日志/offset、reconcile 状态机、SSE、执行器/节点选择）做了多智能体**对抗性 review + 独立复核**，确认并修复了 9 个真实正确性缺陷（均补了回归测试）：

| # | 严重度 | 问题 | 修复 |
|---|---|---|---|
| 1 | high | `drain_attempt` 用非幂等 `files.append`，崩溃丢提交会重复写日志字节、错位 offset | 改用幂等 `files.write_increment(size_bytes, ...)`（重放为 no-op）；`LogGapError`→`missing`。测试 `test_drain_is_idempotent_on_lost_commit_replay` |
| 2 | medium | agent tail 在 `max_bytes` 边界切断多字节 UTF-8 → 永久 U+FFFD 且跳过 | 非 EOF 时回退到 UTF-8 字符边界（`_strip_incomplete_utf8_tail`），下次 pull 重读；含防停滞守卫。测试 `test_tail_utf8_boundary.py` |
| 3 | high | reconcile loop 中“drain 成功”会清空 lost 计时器 → status=unknown 的 attempt 永不升级 lost（卡 running） | drain 成功不再清计时器，仅“正向 /status（running/terminal）”才清。测试 `test_loop.py` |
| 4 | medium | 每 tick 只取一次 `now`，跨阻塞 finalize 复用 → lost 计时/节奏偏移 | `_process` 内每 attempt 重读 `time.monotonic()` |
| 5 | medium | finalize 在单 loop 内同步阻塞，拖慢其它 execution 的 drain/SSE | finalize 改为独立 task + 独立 session 执行（`_finalizing` 去重，`stop()` 收尾） |
| 6 | critical | SSE 端点把请求 DB session 持有整条流（最长 30min）→ 连接池耗尽、拖垮 reconcile loop | reconcile loop 改用**独立 engine/连接池**（与请求池隔离），SSE 长连接再多也不会饿死日志拉取/状态轮询 |
| 7 | high | agent `/run` 返回终态时执行器仍无条件置 `any_running=True` → execution 永卡 running | 仅非终态置 running；全终态时 `rollup_execution_status` 收口。测试 `test_run_immediate_terminal_status_rolls_up_not_stuck` |
| 8 | high | agent `/run` 返回 `unknown` → `attempt.status=None`，PG NOT NULL 整单回滚 | `AGENT_TO_ATTEMPT.get(...) or ATTEMPT_RUNNING`，绝不写 NULL。测试 `test_run_unknown_status_never_writes_null` |

> 这些缺陷都属于“测试与 smoke 不易暴露”的边界/并发/崩溃语义（崩溃重放、UTF-8 边界、lost 计时复位、阻塞 finalize、SSE 连接占用、/run 即终态）。修复后全量 **179 passed**、ruff clean。
>
> 另：Codex 第 1 轮 review（`02-review.md`）又指出 agent 状态判定 P1 与 SSE 连接 P2，已修复，见 `03-review-response.md`。

## 5. 实测运行记录

- **全量 Python**：`179 passed`（server 88 / agent 75 / protocol 16）。
- **ruff**：All checks passed。
- **web**：vitest 7 passed；`vue-tsc` typecheck + vite build 通过。
- **迁移**：真实 PostgreSQL 空库→head 及 downgrade/upgrade 往返通过。
- **compose smoke**：见 §2.2（PASSED 14/14）。

## 6. 已知限制 / 环境说明

- agent 真实 scrapyd 子进程的 spawn/conf/父死信号/回收路径不在单测覆盖（单测用 fake scrapyd），
  由 compose smoke 用真实 scrapyd 覆盖。
- demo egg 的 sha256 跨重建不可复现（bdist_egg 内嵌 .pyc 时间戳）；committed egg 为权威产物，
  compose smoke 缺失时可在 agent 容器内重建（脚本已内置 fallback）。
- 前端构建主 chunk >500kB（Element Plus，未做 code-split）——既有现象，非本阶段引入。

## 7. Codex 复现路径

```bash
# 后端 + 协议 + 前端
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test && corepack pnpm --filter web build

# 迁移（需 db）
scripts/dev-db.sh up
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot \
  ../../.venv/bin/alembic upgrade head

# 端到端（clean volume；构建镜像）
bash scripts/smoke-phase1.sh
```
