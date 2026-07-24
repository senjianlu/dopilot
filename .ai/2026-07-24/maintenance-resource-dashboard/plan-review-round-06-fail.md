# Plan 评审:第 06 轮

## 问题清单
- [plan-blocker] R-01 PostgreSQL 板块故障可能连带击穿 Agent 板块，违反逐板块降级硬约束
  - 详情:定位：§2 `collect_snapshot(session, settings, redis)` 及 TC-01～TC-04。方案要求各板块独立 try/except，但 PostgreSQL 与 agents 都通过同一个 AsyncSession 查询；真实 PostgreSQL 中，一条 SQL 执行失败后事务会进入 aborted 状态，仅捕获异常而不 rollback，后续 nodes 查询仍会失败。因此 PG 专有统计或任一表查询故障可能让 agent scope 一并不可用。请在方案中明确数据库板块间的事务隔离方式，例如由 loop 传入 sessionmaker 并为 postgres/agents 分别创建 session，或在失败后可靠 rollback；同时增加用例，注入 PostgreSQL 查询失败并断言 agent、server、redis 板块仍正常返回。

## 总评
证据契约本身合规：17 条用例均逐条声明档位与证据形态，自动化项全部为 A 档，C 档为 0，且多数关键异常和边界路径已有覆盖。但数据库采集的故障隔离设计与方案明确写出的硬约束冲突，需先修订方案及对应测试再进入实现。

VERDICT: fail
