# Plan 评审:第 05 轮

## 问题清单
- [plan-blocker] R-01 命令流年龄使用了不会作用于命令流的保留策略，仪表盘会产生无法通过清扫消除的告警
  - 详情:plan.md:153-159 将 LOG_STREAM、EVENT_STREAM 及每个 agent 的 command_stream 首条目年龄统一对比 redis.log_retention_seconds，并解释为“XTRIM 失效时变红”；但现有 trim_log_streams 仅清理 LOG_STREAM 与 EVENT_STREAM（apps/server/dopilot_server/services/maintenance.py:269-302），自动清扫和 sweep-now 都不会按时间裁剪命令流。旧命令可能仍是待投递事实，也不应未经投递语义设计直接按日志保留期删除。因此 command stream 会出现操作员无法通过三件套消除的红色年龄告警。方案应把命令流限定为长度/stream_maxlen_commands 指标，排除其 log_retention_seconds 年龄告警；若确需年龄告警，必须先另行定义兼顾待投递命令的清理策略及测试。
- [major] R-02 生产 PostgreSQL 专有容量采集路径没有任何自动化验收覆盖
  - 详情:plan.md:140-152 把 pg_total_relation_size 与 pg_database_size 作为 PostgreSQL 资源板块的核心数据来源，但 TC-01 明确只在 SQLite 验证这些值为 null，plan.md:346-348 又明确承认 PostgreSQL 真值路径不测试。现有测试因方言分流不会执行新增 SQL，无法发现函数签名、标识符解析、返回值转换或权限异常导致整个 postgres scope unavailable 的问题；这不是边缘路径，而是生产唯一数据库上的主要验收路径。应增加 A 档 PostgreSQL 集成用例，至少对实际迁移后的五张表执行采集并断言关系大小、数据库大小为有效非负值；若测试环境不能启动 PostgreSQL，则应采用能实际执行/确证该 SQL 的自动化方案，而不能仅以 SQLite 分支或既有 idiom 代替。

## 总评
方案的 rawf 轮次授权、逐条证据档位与证据形态均符合工作流约定，C 档为 0，主要异常路径也有覆盖。但 Redis 命令流告警语义与既有清扫能力冲突，且生产 PostgreSQL 容量采集核心路径未被测试，因此本轮必须 fail 并修订方案后重评。

VERDICT: fail
