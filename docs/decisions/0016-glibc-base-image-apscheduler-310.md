# 0016:glibc 基础镜像（非 Alpine）；APScheduler 3.10.x

- 日期:2026-06-17
- 背景:两处从 scrapydweb 行为观察中提炼的依赖/镜像约束——(1) 子进程
  父死信号（`prctl(PR_SET_PDEATHSIG)`）依赖 `libc.so.6`，musl（Alpine）
  不满足，会失去父死子亡保护产生孤儿进程；(2) APScheduler 3.6.0 依赖
  `pkg_resources`，`setuptools>=81` 已将其移除，属历史包袱。
- 决定:
  - dopilot 基础镜像使用 **glibc 系（`python:3.12-slim`/debian）**，禁用
    Alpine——凡实现父死信号类子进程控制（agent/executors）都依赖 glibc。
  - dopilot 使用 **`APScheduler>=3.10,<4`**（importlib 实现、无
    `pkg_resources` 依赖），约束写在 `apps/server/pyproject.toml`；
    `setuptools<81` 仅是外部复跑 scrapydweb 参考时的临时手段，不进 dopilot
    依赖。
- 影响:
  - Dockerfile 基础镜像选型不可改为 musl 系。
  - 依赖组织按 monorepo（[0005](0005-monorepo-apps-packages.md)）分散在各
    `pyproject.toml`；解析易出事故的依赖（如 `psycopg`）可 `==` 精确钉死并
    注明理由。
