# 04 · 阶段 1 Codex Review（第 2 轮）

> Review date: 2026-06-18
>
> Source response: `docs/phases/phase-1/03-review-response.md`

## 1. 验收结论

**暂不通过。**

上一轮 review 的两个问题已经按预期修复：

- P1：`scrapyd` 不可达时不再因为 log 文件存在而误判 `finished`，现在返回 `unknown`。
- P2：SSE stream 不再使用请求生命周期绑定的 DB session，改为短生命周期 preflight session。

但本轮复跑 Docker smoke 时发现一个新的阻断项：server 镜像在 `pip wheel` 阶段无法稳定解析 `psycopg[binary]>=3.1`，导致 `docker compose up -d --build` 失败。Phase 1 的交付要求包含 compose smoke，因此在 Docker 构建可复现通过前不能验收。

## 2. 已复跑命令

```bash
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests
```

结果：`179 passed`

```bash
.venv/bin/ruff check apps packages
```

结果：`All checks passed`

```bash
corepack pnpm --filter web test
```

结果：`7 passed`

备注：仍有 `Failed to resolve directive: loading` warning，非本轮阻断。

```bash
corepack pnpm --filter web build
```

结果：通过。

备注：仍有 Vite chunk size warning，非本轮阻断。

```bash
cd deploy/docker && docker compose config
```

结果：通过。

```bash
bash scripts/smoke-phase1.sh
```

结果：失败，未进入应用链路；失败发生在镜像构建阶段。脚本执行了 teardown，随后 `docker compose ps --all` 无残留容器。

我重试了两次：

- 第一次失败在 `files.pythonhosted.org` 下载超时，属于网络不稳定。
- 第二次失败为 `ResolutionImpossible`，属于依赖解析/锁定问题，需要修复。

## 3. 已确认修复项

### 原 P1 · scrapyd 不可达误判 finished

位置：

- `apps/agent/dopilot_agent/runners/scrapyd.py:163`
- `apps/agent/dopilot_agent/runners/scrapyd.py:167`
- `apps/agent/dopilot_agent/runners/scrapyd.py:174`

当前 `ScrapydError` 分支直接返回 `AttemptStatus.unknown`，log-exists 启发式只保留在 `listjobs` 成功返回之后。这符合上一轮 review 要求。

回归测试已覆盖：

- `apps/agent/tests/test_runner.py::test_status_unknown_when_scrapyd_unreachable_even_with_log`
- `apps/agent/tests/test_api_run_status.py::test_status_and_tail_not_finished_when_scrapyd_unreachable`

### 原 P2 · SSE 长连接占用请求 DB session

位置：

- `apps/server/dopilot_server/api/v1/executions.py:39`
- `apps/server/dopilot_server/api/v1/executions.py:207`
- `apps/server/dopilot_server/api/v1/executions.py:240`
- `apps/server/dopilot_server/api/v1/executions.py:335`
- `apps/server/dopilot_server/app.py:81`
- `apps/server/dopilot_server/app.py:84`

当前 `stream_logs()` 通过 `get_request_sessionmaker` 获取 sessionmaker，并在返回 `StreamingResponse` 之前完成短生命周期 DB preflight。generator 只读文件和 SSE 队列。这符合上一轮 review 要求。

回归测试已覆盖：

- `apps/server/tests/test_sse.py::test_normal_api_works_while_sse_stream_open`

## 4. 新阻断问题

### P1 · Docker server 镜像依赖解析不稳定，compose smoke 无法构建

位置：

- `apps/server/pyproject.toml:16`
- `deploy/docker/Dockerfile.server:22`

当前 server 依赖声明为：

```toml
psycopg[binary]>=3.1
```

Docker 构建时 `pip wheel --wheel-dir=/wheels ./packages/protocol ./apps/server` 需要在线解析并下载最新依赖。第二次 smoke 复跑时，pip 对 `psycopg[binary]>=3.1` 进行了大量 backtracking，最终失败：

```text
ERROR: Cannot install psycopg[binary]==3.1 ... psycopg[binary]==3.3.4 because these package versions have conflicting dependencies.
ERROR: ResolutionImpossible
Dockerfile.server:22
RUN pip wheel --wheel-dir=/wheels ./packages/protocol ./apps/server
```

这不是应用运行时失败，但它会阻断 clean-volume `docker compose up -d --build`，因此阻断 Phase 1 验收。

建议修复：

- 固定 server 的 PostgreSQL driver 版本，避免 Docker 构建每次解析最新 `psycopg[binary]>=3.1`。
- 推荐将依赖收敛为明确版本对，例如 `psycopg[binary]==3.3.4`，或显式声明 `psycopg==3.3.4` 与 `psycopg-binary==3.3.4`。
- 更长期的最佳实践是为 Python 镜像构建引入 constraints/lock 文件，Dockerfile 使用同一份 constraints 构建，避免 smoke 受上游新版本影响。
- 修复后必须重新跑 `bash scripts/smoke-phase1.sh`，并确认进入应用链路、最终 `SMOKE PASSED`。

## 5. 其他观察

- `docs/phases/phase-1/03-review-response.md` 说 smoke 被 Docker Hub 临时不可达阻塞；本轮实测基础镜像已能解析，新的阻塞点是 server Python 依赖解析。
- agent 镜像在第二次重试中构建成功；失败集中在 server/migrate 镜像的 server wheel 构建阶段。

## 6. 下一步

Claude 需要先修复 Docker server 镜像依赖解析问题，再复跑：

```bash
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
bash scripts/smoke-phase1.sh
```
