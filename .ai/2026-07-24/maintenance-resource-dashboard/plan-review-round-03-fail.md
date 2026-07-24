# Plan 评审:第 03 轮

## 问题清单
- [major] R-01 Agent 在线状态判定使用了不存在的 `online` 值，会把真实在线节点全部标成 unavailable
  - 详情:定位：实现方案 §2“统一状态契约”及 TC-04。现有 `nodes.status` 契约是 `healthy | degraded | unhealthy | unknown`（`apps/server/dopilot_server/nodes/service.py`），并不存在 `online`；数据库字段也由该聚合逻辑写入。按当前方案实现，真实的 healthy/degraded 节点都会命中“status 非 online”，导致磁盘指标不可用。应明确以心跳新鲜度或现有状态枚举判定可用性，并将 TC-04 的节点状态改为真实枚举，覆盖 healthy、degraded、unhealthy/超时及无样本。
- [major] R-02 保留年龄指标没有复用实际清扫谓词，会产生无法由清扫消除的错误告警
  - 详情:定位：实现方案 §2 PostgreSQL 指标及 TC-01/TC-02。方案以 `MIN(tasks.created_at)` 衡量终态任务年龄，但 `cleanup_terminal_data` 实际使用 `finished_at`，仅在其为空时回退 `created_at`（`apps/server/dopilot_server/services/maintenance.py:77`）；方案又以 `event_audit.created_at` 衡量审计保留，而 `prune_event_audit` 实际按 `processed_at` 删除（同文件约 253 行）。长时间运行后刚结束的任务或较早创建但较晚处理的审计行会持续误报红色。应让统计查询与两个清扫函数共享或严格复制同一 effective-time 谓词，并增加对应反例测试。还需定义 `retention_days=0`、`event_audit_retention_days=0`、`log_retention_seconds=0` 以及 `maintenance.enabled=false` 时的 disabled/unknown 语义，避免把明确关闭的限制计算成 critical。
- [major] R-03 Server 日志用量按硬编码目录采集，违背可配置存储根目录契约
  - 详情:定位：实现方案 §2 server 采样写死 `/server-data/logs`。现有权威配置是 `settings.logs.root_dir`，且 `settings.server.data_dir` 明确与日志、artifact 根目录彼此独立（`apps/server/dopilot_server/config/settings.py`）。自定义 `logs.root_dir` 的部署将展示错误目录的用量，甚至显示零用量。应从 `settings.logs.root_dir` 和 `settings.artifacts.root_dir` 采集，并在 TC-01 使用与 `server.data_dir` 不同的临时根目录验证配置确实生效。

## 总评
方案的证据契约合规：16 条用例均逐条声明档位和证据形态，C 档为 0，且包含多类故障路径。但节点状态枚举、保留时间谓词及存储目录来源与现有实现契约冲突，会直接造成仪表盘长期误报，因此本轮应 fail 并修订后重评。

VERDICT: fail
