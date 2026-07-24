# 0007:PostgreSQL 唯一数据库；日志正文落文件不入库

- 日期:2026-06-17
- 背景:scrapydweb 参考实现使用 4 个 SQLite 库；dopilot 需要一个可运维、可
  备份的持久化选型，且实时日志的体量不适合塞进关系库。
- 决定:**PostgreSQL 是 dopilot 唯一数据库**。server 是唯一持有数据库连接、
  事务与迁移（SQLAlchemy + 裸 Alembic，迁移在 `apps/server/migrations/`）的
  角色；agent 与 web 永不直连数据库。PostgreSQL 存业务数据 + **日志索引/
  offset/状态**（表 `execution_log_files`）；**日志正文不入 PostgreSQL**，
  以文件形式落 server 本地卷
  `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`，带
  保留策略。被否掉的备选：SQLite（不作为正式运行路径）、日志正文入库。
- 影响:
  - **Redis 是消息总线/瞬时传输层，不是 dopilot 数据库**：不持久化业务真相；
    agent 经 Redis 与 server 通信，仍不直连 PostgreSQL
    （见 [0008](0008-redis-streams-agent-communication.md)）。
  - 备份必须同时覆盖 PostgreSQL 与 `/server-data/logs` 卷，两者缺一不可；
    Redis 不是备份目标。
  - 删库重建不是 dopilot 的迁移策略；schema 演进一律走 Alembic。
