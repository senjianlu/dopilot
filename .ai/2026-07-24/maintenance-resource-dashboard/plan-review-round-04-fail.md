# Plan 评审:第 04 轮

## 问题清单
- [major] R-01 Agent 可用性方案读取持久化 `nodes.status`，会把停止心跳后的节点长期误判为健康。
  - 详情:定位：plan.md「2. Server 采样快照」agents 段及统一状态契约。现有 `upsert_node_heartbeat` 只在收到心跳时写 `Node.status`；真正随时间变化的状态由 `nodes/service.py::_aggregate_node_status(node, now, heartbeat_timeout_seconds)` 在读取时根据 `last_seen_at` 动态计算。因此直接“逐行取 status”后按 healthy/degraded 分支判断，节点断联后数据库中的 healthy 不会自行变成 unhealthy，仪表盘可能持续展示陈旧样本为 ok/stale，而非 unavailable。方案应明确复用/抽取动态状态聚合逻辑（使用当前时间和配置的 heartbeat timeout），并增加“持久化 status=healthy、但 last_seen_at 已超时”的用例；TC-04 目前仅预种五种 status，无法覆盖该回归。
- [major] R-02 `sweep-now` 无法按方案从现有 `trim_log_streams` 得知 XTRIM 失败，响应会虚报或无法如实标记 `stream_trim=failed`。
  - 详情:定位：plan.md「3. API」sweep-now 与 TC-05。现有 `services/maintenance.py::trim_log_streams` 在每个流内部捕获所有 XTRIM 异常，只记录日志并返回缺少失败流的 dict，不向调用者抛错；方案又要求复用该函数、不复制逻辑，并称用步骤级 try/except 将 XTRIM 异常映射为 failed。端点的 try/except 实际捕获不到该异常，而且空/部分结果没有显式失败原因，无法可靠兑现“逐步如实汇报”。应在方案中定义可兼容自动 loop 的结构化逐流结果/失败信号（或明确以缺失的预期流判失败并区分 disabled/skipped），再让 endpoint 聚合状态；TC-05 应同时断言单流失败和部分成功的响应。
- [major] R-03 方案把 `logs.retention_days=0` 定义为关闭保留，却仍让手动及自动清扫按 cutoff=now 执行，存在删除全部终态任务的语义冲突。
  - 详情:定位：plan.md「统一状态契约」称 `logs.retention_days=0` 为“明确关闭”，但「sweep-now」无条件调用 `cleanup_terminal_data(cutoff=now-retention_days)`；现有 `RetentionSweepLoop.sweep_once` 也无 0 值短路。按当前服务语义，0 天会使几乎所有终态任务立即满足删除条件，而不是关闭清理。仅让仪表盘显示 limit=null/ok 会掩盖真实危险。方案必须选择并统一语义：若 0 确为关闭，需同时修改/测试自动 loop 与 sweep-now 的 skip 行为及响应；若 0 表示立即清理，则删除“关闭”表述并按该含义展示告警。TC-02 目前只测指标，TC-05/TC-07 未覆盖此边界。
- [major] R-04 plan 未经用户明确授权将 plan 评审上限从默认 3 轮提高到 10 轮，直接违反 rawf 工作流硬规则。
  - 详情:定位：plan.md frontmatter `plan_review_max_rounds: 10`。`CLAUDE.md`、`.claude/skills/rawf-plan/SKILL.md` 与 `.ai-workflow/scripts/plan-review.sh` 均规定该字段只能在用户明确要求放宽时写入；当前评审请求没有给出该授权。应删除该字段以恢复默认 3 轮，除非先取得用户对具体上限的明确授权。

## 总评
方案的测试表已逐条声明档位和证据形态，全部可自动化项均为 A 档、无 C 档，证据契约本身合规；异常路径也覆盖较广。但 Agent 离线判定、Redis 清扫失败汇报和 0 天保留语义存在会造成错误运维结论或危险清理行为的方案缺口，且评审轮次配置违反既有 rawf 硬规则，因此本轮 fail。

VERDICT: fail
