# 0004:server/agent 两种 Docker 角色，统一镜像 `rabbir/dopilot`

- 日期:2026-06-17
- 背景:dopilot 需要一个调度中枢和若干执行节点，且都要求 Docker 部署；镜像
  怎么拆（一镜像多角色 vs 每角色一镜像）影响构建、发布与升级成本。
- 决定:分 **server**（Web + 调度中枢）与 **agent**（worker 执行器）两种部署
  角色，均以 Docker 部署；构建并推送**一个统一镜像 Docker Hub
  `rabbir/dopilot:latest`**，server / agent / migrate 容器共用该镜像，由启动
  命令选择角色（`dopilot-server` / `dopilot-agent` / `alembic upgrade head`）。
  被否掉的备选：按角色拆分 `rabbir/dopilot-agent` 等多镜像——同仓同版本下
  徒增发布面。
- 影响:
  - ⚠️ 镜像命名空间 `rabbir`（Docker Hub 账号）≠ git `origin` 的
    `senjianlu`，两者无关；文档/CI 中绝不用 `senjianlu` 作镜像前缀。
  - 镜像内同时含 server、agent、protocol、scrapy/scrapyd 运行时、Alembic
    迁移与 Web 静态产物；CI（GitHub Actions）负责构建推送，另有
    `rabbir/dopilot-py-base` / `rabbir/dopilot-web-base` 依赖基础镜像按
    deps-hash 固定。
  - 部署形态见 `../architecture/05-deployment.md`。
