# Plan 评审:第 18 轮

## 问题清单
- [major] R-01 迁移用例与现有 PostgreSQL fixture 共用数据库，却未定义可重复建立 0013 基线的隔离或重置步骤
  - 详情:定位：plan.md:320-324、TC-15（:351）、TC-25（:361）及 apps/server/tests/conftest.py:563-584。TC-15 直接以“库停在 0013”为前置执行 upgrade 0014；但 TC-25 中更早运行的 PG 用例会对同一数据库执行 Base.metadata.drop_all/create_all/drop_all，且不清理 alembic_version，可能留下“版本标记为 0013、业务表已删除”的不一致状态。此后 TC-15 仅应用 0014，会在 ALTER TABLE schedules 处失败；空库、已升级库和重复执行同样缺乏稳定基线。请明确使用隔离数据库/schema，或在测试内可靠重置 schema 与版本表、执行 upgrade 0013、插入存量行后再验证 0014，并以 finally 清理或恢复；独立 TC-15 和全量 TC-25 均应覆盖该可重复路径。

## 总评
并发准入、锁下重读、跨来源额度、前端异常路径及逐条证据契约已基本自洽，A/B/C 分配合规。当前迁移测试的数据库生命周期与既有 PG fixture 冲突，会直接阻断可信的全量测试证据。

VERDICT: fail
