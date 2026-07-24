# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 指标模型没有把多项既有硬上限映射为可比较的当前值，无法实现“当前值 vs 临界值”的核心目标
  - 详情:定位：实现方案 §2 的 postgres/server 条目及统一状态契约。方案仅采集 server 日志目录总字节和 PostgreSQL 各表行数，却没有与 `[logs].max_file_bytes`、`[logs].retention_days`、`[maintenance].event_audit_retention_days` 对应的同量纲指标；null-limit 条目还被规定为恒 `ok`。目录总字节不能与单文件上限比较，表行数也不能与保留天数比较，因此超限或保留清扫失效时仪表盘仍可能显示绿色。这也偏离 audit-inventory D3 明确要求纳入这些配置上限的设计。应在方案阶段补充同量纲指标，例如最大单日志文件字节数对 `max_file_bytes`、最老可清理记录年龄对相应 retention days，并同步修订响应契约、等级计算及边界测试。
- [major] R-02 手动 retention sweep 未定义步骤级故障隔离，测试也只覆盖成功和 Redis 缺失路径
  - 详情:定位：实现方案 §3 `POST /maintenance/sweep-now` 与 TC-05。既有 `RetentionSweepLoop.sweep_once` 的约定是三个步骤独立防护，前一步失败不能跳过后续步骤；新方案仅描述用同一请求依次调用三个 service，响应结构也没有表达单步失败，意味着 cleanup 或 audit prune 抛错时后续维护可能完全不执行。TC-05 只验证全部成功及 Redis 不存在的正常跳过，没有注入 cleanup、prune、XTRIM 的异常来验证隔离和响应语义，属于多步骤运维操作只测 happy path。应明确每步失败后的继续执行、事务回滚和响应/HTTP 语义，并增加各步骤异常的 A 档测试。

## 总评
方案的 rawf 证据契约本身合规：16 条用例均逐条声明档位与证据形态，C 档为 0，异常路径也有一定覆盖。但核心资源指标与既有上限没有完整、同量纲地对应，且新增手动清扫缺少关键故障语义和测试，因此当前不能进入实现。

VERDICT: fail
