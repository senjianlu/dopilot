# 02 · 阶段 1 Codex Review

> Review date: 2026-06-18
>
> Source report: `docs/phases/phase-1/01-implementation-report.md`

## 1. 验收结论

**暂不通过。**

Phase 1 的主链路已经基本成型，单元测试、前端测试、构建、compose 配置与真实 Docker smoke 都已复跑通过。但代码审阅发现一个会错误结束运行中任务的状态判定问题，和一个 SSE 长连接可能耗尽普通请求 DB 连接池的资源问题。第一个问题会破坏 Phase 1 对“真实状态机 / 重启语义 / 不出现无解释 running”的目标，需要修复后再验收。

## 2. 已复跑命令

```bash
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests
```

结果：`176 passed`

```bash
.venv/bin/ruff check apps packages
```

结果：`All checks passed`

```bash
corepack pnpm --filter web test
```

结果：`7 passed`

备注：Vue 测试输出有 `Failed to resolve directive: loading` warning，但未导致测试失败。建议后续补齐 Element Plus loading directive 的 test setup。

```bash
corepack pnpm --filter web build
```

结果：通过。

备注：Vite 输出 chunk size warning，当前不是 Phase 1 阻断项。

```bash
cd deploy/docker && docker compose config
```

结果：通过。

```bash
bash scripts/smoke-phase1.sh
```

结果：`SMOKE PASSED`，脚本汇总 `passed=14 failed=0`。脚本结束后 `docker compose ps --all` 无残留容器。

## 3. 阻断问题

### P1 · scrapyd 不可达时，agent 可能把运行中任务误判为 finished

位置：

- `apps/agent/dopilot_agent/runners/scrapyd.py:163`
- `apps/agent/dopilot_agent/runners/scrapyd.py:167`
- `apps/agent/dopilot_agent/runners/scrapyd.py:169`
- `apps/agent/dopilot_agent/runners/scrapyd.py:170`

当前 `_resolve_status()` 在 `listjobs` 抛 `ScrapydError` 时，只要本地 log 文件存在，就返回 `finished`：

```python
except ScrapydError:
    if Path(state.log_path).exists():
        return AttemptStatus.canceled if state.canceled else AttemptStatus.finished
    return AttemptStatus.unknown
```

这会把“scrapyd 子进程崩溃 / 暂时不可达，但 job 原本仍在 running 且已经写过日志”的场景误判为正常完成。随后 server 侧 `logs/loop.py` 会把 terminal status 送进 final drain，并最终把 execution rollup 成 `complete`。这会隐藏真实失败，也会让用户看到一个成功完成的任务，而不是 lost/failed/unknown。

这与 Phase 1 的目标冲突：阶段文档要求容器重启、agent 可达但状态无法解析、scrapyd 不可达等场景必须进入明确状态，而不能靠 log 文件存在推断成功。

建议修复：

- `ScrapydError` 代表 scrapyd 状态不可判定时，应返回 `unknown` 或显式 `failed/lost` 语义，不应返回 `finished`。
- “job 不在 running/pending/finished 列表但 log 存在”可以作为重启恢复的 best-effort 分支保留，但它只适用于 `listjobs` 成功返回、scrapyd 明确可达的情况。
- 补测试覆盖：`listjobs` transport error / non-ok 时，即使 log 文件存在，`GET /status` 和 `GET /logs/tail.finished` 也不能返回 finished。

## 4. 非阻断但建议修复

### P2 · SSE endpoint 仍可能持有请求 DB session 直到长连接结束

位置：

- `apps/server/dopilot_server/api/v1/executions.py:191`
- `apps/server/dopilot_server/api/v1/executions.py:199`
- `apps/server/dopilot_server/api/v1/executions.py:218`
- `apps/server/dopilot_server/api/v1/executions.py:315`
- `apps/server/dopilot_server/app.py:67`
- `apps/server/dopilot_server/app.py:68`

`stream_logs()` 注入 `session: AsyncSession = Depends(get_session)`，先用它查询 execution / attempt / log_file，再返回 `StreamingResponse(generator())`。FastAPI 的 yield dependency 通常会在 response 完成后释放；对 SSE 来说，这可能意味着 session 生命周期跟随长连接。代码已经通过独立 loop engine 避免 reconcile loop 被饿死，但普通请求池仍可能被多个 SSE 长连接占住，影响 list/detail/cancel/auth 等普通 API。

建议修复：

- 不要在 SSE endpoint 上使用请求生命周期绑定的 DB dependency。
- 在返回 `StreamingResponse` 前，用短生命周期 session 取出 primitive 数据并关闭 session。
- 或把 preflight 查询拆到显式 `async with sessionmaker() as session:` 块里，确保构造 response 前已经释放连接。
- 补一个连接池很小的集成测试，打开多个 SSE 后验证普通 API 仍能取到 DB 连接。

## 5. 其他观察

- `docs/phases/phase-1/01-implementation-report.md` 中测试数量前后出现 `168 passed` 与 `176 passed` 两种说法。实际复跑结果是 `176 passed`，建议统一报告文本。
- Web 测试 warning：`Failed to resolve directive: loading`。建议在 Vitest setup 中注册或 stub `v-loading`。
- 前端 bundle chunk size warning 暂不影响 Phase 1 验收，但后续阶段应考虑 route-level split 或依赖拆分。

## 6. 下一步

Claude 需要先修复 P1，并补上对应回归测试。修复后 Codex 应至少复跑：

```bash
.venv/bin/pytest apps/agent/tests apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
bash scripts/smoke-phase1.sh
```
