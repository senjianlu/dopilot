# 0005:monorepo：`apps/` + `packages/` 布局

- 日期:2026-06-17
- 背景:server、agent、web 三个可部署单元加共享协议，拆多仓会带来协议同步
  与版本对齐成本；单仓则需要清晰的布局约定。
- 决定:server、agent、web 在**同一仓库**开发，采用 `apps/` + `packages/`
  布局：`apps/server/dopilot_server`、`apps/agent/dopilot_agent`、`apps/web`，
  server↔agent 共享协议在 `packages/protocol`（可选客户端 SDK 在
  `packages/client`），部署物在 `deploy/`，配置样例在 `configs/`。不拆分多仓。
- 影响:
  - Python 应用各自带 `pyproject.toml`（依赖独立声明），根 `pyproject.toml`
    只放共用 dev 工具配置（pytest/ruff），不是可安装包。
  - Docker 构建上下文为仓库根，一次提交产出一个镜像
    （[0004](0004-two-docker-roles-unified-image.md)）。
  - 权威目录树见 `../architecture/README.md`。
