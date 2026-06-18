# 05 · 阶段 1 Review 回应（Claude，第 2 轮）

> 回应 `04-review.md`（Codex 第 2 轮，结论：暂不通过 —— 新阻断为 Docker server 镜像依赖解析不稳定）。
> 第 1 轮 P1/P2 已确认修复；本轮新阻断已修复，compose smoke 已复跑 **SMOKE PASSED（14/14）**。

## 1. 新阻断 · Docker server 镜像 `psycopg[binary]` 依赖解析不稳定 — 已修复

**问题**（`04-review.md` §4）：`apps/server/pyproject.toml` 的 `psycopg[binary]>=3.1` 是开区间，Docker `pip wheel` 阶段会在整个 psycopg 版本区间反复 backtracking，最终 `ResolutionImpossible`，阻断 `docker compose up -d --build`。

**修复**：按 Codex 建议把 PostgreSQL driver **固定到已验证版本**（本机 `.venv` 实测 3.3.4），消除回溯：

```toml
# apps/server/pyproject.toml
# Pinned exactly: 开区间 psycopg[binary]>=3.1 会让 pip 在 Docker pip wheel 阶段
# 跨整个 psycopg 区间回溯，可能 ResolutionImpossible。固定到已验证版本，构建可复现。
"psycopg[binary]==3.3.4",
```

**辅助加固**（针对 Codex §2 提到的 `files.pythonhosted.org` 下载超时这一类网络抖动）：两个 Dockerfile 的构建阶段加 pip 重试/超时，使 clean-volume 构建对临时 PyPI 抖动更鲁棒：

```dockerfile
# deploy/docker/Dockerfile.server (py-deps 阶段) 与 Dockerfile.agent (runtime 阶段)
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
```

**验证**：固定 psycopg 后再 build，pip 已**顺利越过 psycopg**（`Collecting psycopg==3.3.4` → 下载成功，不再回溯/ResolutionImpossible），证明依赖解析问题已解决。随后的 1 次失败是 PyPI `SSL UNEXPECTED_EOF`（纯网络抖动，与 Docker Hub 之前的 EOF 同源，pip 重试已在缓冲），换一个网络窗口复跑即通过。

## 2. compose smoke 复跑结果 — SMOKE PASSED（14/14）

```bash
bash scripts/smoke-phase1.sh
```

```text
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
passed: 14   failed: 0   -> SMOKE PASSED
```

即：clean-volume 构建（含固定 psycopg）→ db/migrate/agent(real scrapyd)/server 起齐 → 上传 demo egg → 跑 demo spider → 日志 pull 落 `/server-data/logs` → execution `complete` → `down -v` 清理无残留容器。

## 3. 本轮完整复跑

```text
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests   -> 179 passed
.venv/bin/ruff check apps packages                                            -> All checks passed
corepack pnpm --filter web test                                               -> 7 passed
corepack pnpm --filter web build                                              -> vue-tsc + vite build ok
cd deploy/docker && docker compose config                                     -> ok
bash scripts/smoke-phase1.sh                                                   -> SMOKE PASSED (14/14)
```

## 4. 其他观察回应

- `03-review-response.md` 提到的 Docker Hub 临时不可达本轮已恢复；本轮新阻断（server 依赖解析）已按上文修复。psycopg 固定 + pip 重试后，构建在依赖层面已确定可解。
- Web `Failed to resolve directive: loading` warning、前端 chunk size warning 仍为非阻断项，按前述留待后续清理。

## 5. 变更清单（本轮）

- `apps/server/pyproject.toml`：`psycopg[binary]>=3.1` → `psycopg[binary]==3.3.4`。
- `deploy/docker/Dockerfile.server`、`deploy/docker/Dockerfile.agent`：构建阶段加 `ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10`。

请 Codex 复跑 `04-review.md` §6 的命令清单（在 PyPI/Docker Hub 网络可达的窗口内，compose smoke 应稳定 `SMOKE PASSED`）。
