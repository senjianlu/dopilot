# 0015:TOML 配置 + env 覆盖；不继承 scrapydweb 配置形态与清目录行为

- 日期:2026-06-17
- 背景:scrapydweb 参考实现把配置文件名硬编码（`scrapydweb_settings_v11.py`）
  且仅从 `os.getcwd()` 查找，并在 import 时清空 `parse/`、`deploy/`、
  `schedule/` 目录下的 `*.*` 文件。这两个实现怪癖都不适合容器化的
  greenfield 平台。
- 决定:dopilot 使用**自有 TOML 配置加载器**：配置文件在 `configs/` 下
  （`server.example.toml` / `agent.example.toml`），经 `DOPILOT_CONFIG` 显式
  指定路径加载；Docker 镜像内置角色默认配置路径（`/app/configs/*.toml`），
  部署主要用 `DOPILOT_*` 环境变量覆盖（env 优先于 TOML；例外：
  `token_secret` 仅 TOML）。**不沿用** cwd 硬编码文件名加载。同时明确
  **不继承"启动即清目录"的破坏性 import 行为**——瞬态中转与持久数据在
  路径设计上物理隔离。
- 影响:
  - `load_settings()` 无副作用（不建文件、不生成密钥；参见
    [0011](0011-auth-boundaries.md) 阶段 2.2.4 的运行时生成边界）。
  - 配置键属 dopilot 自有领域命名，仅参考 scrapydweb 配置键的语义，不搬
    其形态（[0001](0001-scrapydweb-behavior-reference-only.md)）。
