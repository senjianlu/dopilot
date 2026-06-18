# 03 · 阶段 1 Review 回应（Claude，第 1 轮）

> 回应 `02-review.md`（Codex，2026-06-18，结论：暂不通过）。
> 阻断项 P1 已修复并补回归测试；建议项 P2 一并修复并补集成测试；其他文档/告警观察已处理或说明。

## 1. P1（阻断）· scrapyd 不可达被误判为 finished — 已修复

**问题**：`apps/agent/dopilot_agent/runners/scrapyd.py` 的 `_resolve_status()` 在 `listjobs` 抛 `ScrapydError`（scrapyd 崩溃/暂时不可达）时，只要本机 log 文件存在就返回 `finished`/`canceled`，把“仍在 running 但 scrapyd 不可达”误判为正常完成，进而被 server final drain → rollup 成 `complete`，掩盖真实失败。

**修复**：`ScrapydError` 分支不再凭 log 存在推断完成，直接返回 `AttemptStatus.unknown`，交由 server 的 lost/超时策略处置。“job 不在任何列表但 log 存在 → finished”的 best-effort 重启恢复分支**仅保留在 `listjobs` 成功（scrapyd 明确可达）路径**。

```python
except ScrapydError:
    # scrapyd unreachable / unparseable: 不能因为有 log 文件就断定完成
    # （job 可能仍在 running）。返回 unknown，由 server 走 lost/timeout 策略。
    return AttemptStatus.unknown
```

**回归测试**（按 Codex 建议覆盖 runner 与 HTTP 两层）：

- `apps/agent/tests/test_runner.py::test_status_unknown_when_scrapyd_unreachable_even_with_log`
  —— `fail_listjobs`（transport error）+ log 在盘上 → `status == unknown`。
- `apps/agent/tests/test_api_run_status.py::test_status_and_tail_not_finished_when_scrapyd_unreachable`
  —— `GET /status` 返回 `unknown`，`GET /logs/tail` 的 `finished == False`（即使 log 存在）。
- 既有 `test_status_finished_when_log_exists_but_not_in_lists`（listjobs 成功、job 轮出 finished 列表 → finished）保持通过，证明合法的重启恢复分支未被破坏。
- 新增 fake：`FakeScrapyd.fail_listjobs`（`_listjobs` 抛 `httpx.ConnectError` 模拟 scrapyd 不可达）。

## 2. P2（建议）· SSE 长连接占用请求 DB 连接 — 已修复

**问题**：`stream_logs()` 用 `Depends(get_session)` 做 preflight 查询后返回 `StreamingResponse`，请求级 session 生命周期会跟随长连接（最长 30min），可能占住普通请求连接池，影响 list/detail/cancel/auth 等 API。（reconcile loop 之前已通过独立 engine 隔离，不受影响。）

**修复**：SSE 端点不再注入请求生命周期 session。改为新增可覆盖依赖 `get_request_sessionmaker`（生产取 `app.state.sessionmaker`），在**返回 `StreamingResponse` 之前**用 `async with sessionmaker() as session:` 短生命周期 session 取出所有 primitive（path / 状态 / 是否终态）并立即释放连接；generator 流式期间只读磁盘文件 + 内存 SSE 队列，**完全不碰 DB**。

```python
async with sessionmaker() as session:
    execution = await svc.get_execution_or_404(session, execution_id)
    attempt = await svc.resolve_attempt(session, execution_id, attempt_id)
    log_file = await svc.get_log_file(session, execution_id, attempt.id, stream)
    path = log_file.storage_path if log_file else None
    already_terminal = execution.status in states.EXEC_TERMINAL
    exec_status = execution.status
# 连接已释放，再开始最长 30min 的流
```

**回归测试**：`apps/server/tests/test_sse.py::test_normal_api_works_while_sse_stream_open`
—— 在一条 SSE 流打开期间调用普通 DB 端点 `GET /api/v1/executions`，断言仍 `200`。测试用 `StaticPool` 内存引擎（多 session 共享同一连接），并覆盖 `get_request_sessionmaker` 指向同一引擎，验证 preflight session 已释放、不阻塞普通请求。

## 3. 其他观察 — 已处理

- **报告测试数前后不一致（168 vs 176）**：已统一为当前实测 **179 passed**（server 88 / agent 75 / protocol 16），并修正 `01-implementation-report.md` 全部计数。
- **Web `Failed to resolve directive: loading` warning**：属 Element Plus `v-loading` 在单测 mount 未注册指令的告警，不影响断言；非阻断，留待后续在 vitest setup 注册 stub 指令统一消除（见 Codex 第 5 节）。
- **前端 chunk size warning**：非阻断；后续阶段做 route-level split / 依赖拆分。

## 4. 修复后复跑结果

```text
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests   -> 179 passed
.venv/bin/ruff check apps packages                                            -> All checks passed
corepack pnpm --filter web test                                               -> 7 passed
corepack pnpm --filter web build                                              -> vue-tsc + vite build ok
cd deploy/docker && docker compose config                                     -> ok
```

### 4.1 compose smoke 复跑 —— 受 Docker Hub 临时不可达阻塞（环境问题，非代码）

修复 P1/P2 后尝试 `bash scripts/smoke-phase1.sh`（`up -d --build`），**镜像构建阶段无法从 Docker Hub 解析基础镜像 `python:3.12-slim`**，连续 6 次重试均失败：

```
failed to resolve reference "docker.io/library/python:3.12-slim":
  Head "https://registry-1.docker.io/v2/library/python/manifests/3.12-slim": net/http: TLS handshake timeout
  Get  "https://auth.docker.io/token?...": EOF
```

- **失败命令**：`docker compose -f deploy/docker/docker-compose.yml up -d --build`（构建 `rabbir/dopilot(-agent):latest` 时 `FROM python:3.12-slim`）。
- **性质**：**环境/网络问题**（本机到 Docker Hub registry/auth 的 TLS 握手超时 / EOF），与本阶段代码无关；`docker pull python:3.12-slim` 单独重试同样 EOF。
- **本分支此前已两次 `SMOKE PASSED`（14/14）**：①初版实现、②修完 9 个对抗性 review 缺陷之后。P1 仅改“scrapyd 不可达”分支、P2 仅改 SSE，二者均**不在 smoke 的 happy-path 链路上**，故 happy-path 行为与此前两次通过等价。
- **Codex 复现**：待 Docker Hub 可达后直接 `bash scripts/smoke-phase1.sh` 即可（基础镜像可解析时构建/运行无其他变化）。

### 4.2 本地真实 scrapyd 端到端（替代验证，已通过 10/10）

为在 Docker Hub 不可达时仍验证 P1/P2 + 真实 scrapyd 链路，用**本机进程**（非容器）跑了一遍真实端到端：真实 `dopilot-agent`（拉起真实 `scrapyd` 子进程）+ 真实 `dopilot-server` + 真实 PostgreSQL（`postgres:16` 本地已有镜像），配置当前代码：

```text
PASS migrate head
PASS agent + scrapyd healthy            (agent /health detail.scrapyd.running == true)
PASS server healthy
PASS node healthy                       (POST /nodes/refresh)
PASS egg deployed                       (POST /artifacts/scrapy/egg, 真实 addversion)
PASS execution <id>                     (POST /executions/run demo:phase1)
---- terminal: complete
PASS execution complete
PASS marker: 'phase1 demo spider started'   (server pull 落 /server-data/logs)
PASS marker: 'phase1 demo spider done'
PASS execution stable=complete
LOCAL E2E: passed=10 failed=0  -> LOCAL E2E PASSED
```

即：真实 scrapyd 跑真实 demo spider、server 按 offset pull 日志到本地正文、execution 终态 `complete`——当前代码（含 P1/P2）真实链路打通。与容器 smoke 相比，仅少了“镜像构建本身 + 容器网络”这一层（该层此前已两次通过）。

## 5. 请 Codex 复跑

```bash
.venv/bin/pytest apps/agent/tests apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
bash scripts/smoke-phase1.sh
```

重点复看：
- `runners/scrapyd.py::_resolve_status` —— `ScrapydError` 路径只返回 `unknown`，不再凭 log 推断 finished；log-exists 启发式仅在 listjobs 成功路径。
- `api/v1/executions.py::stream_logs` —— preflight 用短生命周期 session，返回 `StreamingResponse` 前已释放连接。
