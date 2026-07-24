# 0001:scrapydweb 仅作外部行为参考，绝不进入本仓库

- 日期:2026-06-17
- 背景:dopilot 的功能语义源自 Flask 实现的 scrapydweb（Scrapyd 集群管理平台）。
  需要明确上游代码与 dopilot 代码的边界，否则移植过程中极易把上游的结构、
  命名、依赖形态带进 greenfield 代码；同时 MIT 开源要求仓库内不含上游快照。
- 决定:上游 scrapydweb（`1.6.0` / commit `1341cf9`，公开仓库
  https://github.com/my8100/scrapydweb ）仅作两种用途——(1) **功能层/行为参考**
  （它做了什么、规则是什么），(2) **行为 oracle**（预期行为对照，见 [0017](0017-testing-baseline-own-regression-net.md)）。
  其代码写法、目录结构、模块划分、命名、依赖组织、配置形态**一律不得作为
  dopilot 设计依据**。本仓库**不保留本地快照**（为 MIT 发布已移除
  `reference/scrapydweb/`），需要观察行为时在仓库之外克隆上游。被否掉的备选：
  vendor 一份只读快照在仓库内——与 MIT 发布及"防结构渗透"目标冲突。
- 影响:
  - 上游代码绝不被拉取/内置/import/参与构建；任何 scrapydweb 派生物不得进入
    Docker 构建上下文（`.dockerignore` 与 `pyproject.toml` 仍防御性排除
    `reference/` 路径，该目录已不存在）。
  - 文档中的 scrapydweb `file:line` 引用一律相对上游 1.6.0 / `1341cf9`，是
    外部行为参考引用，不是本仓库路径。
  - git 远程 `upstream` → `my8100/scrapydweb` 仅用于 diff/对照，不合并其历史。
