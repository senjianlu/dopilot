# 0009:实时日志：agent 推 Redis log stream + server 落盘 + SSE，无 WebSocket

- 日期:2026-06-17（初始为 server pull；2026-06-19 随 [0008](0008-redis-streams-agent-communication.md) 翻案为 agent push）
- 背景:实时日志需要从 agent 流回 server 再推到 Web。第一版刻意不用
  WebSocket，且日志正文体量大、不适合入库；通信层翻案后拉取模型也一并翻案。
- 决定:日志由 **agent 经 Redis log stream `dopilot:server:logs` 主动推增量**
  （base64 字节，带 agent 本地文件的逻辑字节 `offset`/`size_bytes`/`eof`），
  **server log consumer 消费后落盘**并更新索引，再经 **server→web SSE** 单向
  推给前端。四个不变量：①第一版**不使用 WebSocket**；②fan-out 到 web 走
  **SSE**；③日志正文落 `/server-data/logs`；④PostgreSQL 只存索引/offset/
  状态（[0007](0007-postgresql-only-log-bodies-on-disk.md)）。`LogSource`
  抽象保留，实现由 `AgentTailLogSource`（server pull）换为 `RedisLogSource`
  （agent push + server consume）。
- 影响:
  - **日志 RPO ≠ 0（接受）**:server 长停或 Redis log stream 裁剪超出保留
    窗口会造成缺片；server 检测 offset gap 时插入可见 gap marker、把该
    attempt 的 `log_integrity` 置为黏性 `partial`。日志完整性与业务状态
    **分离**——日志缺口是可见/可审计事实，永不阻塞执行状态收敛。
  - `last_pulled_offset` 是 server 已消费的 agent 逻辑字节 offset 权威；
    `final_offset` 是 server 文件物理大小（含 gap marker），两者不混用。
  - 日志清理由 server 在 terminal 事件 + bounded drain 后向 agent 投
    `cleanup_logs` 命令触发；agent 不因 XADD 成功就删本地日志。
