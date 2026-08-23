# Plan 评审:第 13 轮

## 问题清单
- [plan-blocker] R-01 日志写入部分失败时 Gauge 会低估实际目录大小，声明的总量硬界仍可被突破。
  - 详情:定位：WP-A `LogsDirGauge`、WP-B `services/logs.py` 及 TC-11b。方案规定“写入异常时不加”，但普通文件写入可能先落下一部分字节，再因 ENOSPC、flush/close 等错误抛异常；此时物理目录已增长而 gauge 保持不变，后续准入会重复使用同一预算并越过 `max_total_bytes`。应采用写前保守预留并按写后实测释放差额，或在成功和异常路径都用写前/写后 `stat` 差值更新 gauge；增加“部分写入后抛异常”的测试，而非只测未写入即抛错时 value 不变。
- [plan-blocker] R-02 统一锁序未覆盖 Execution 与既有终态写入者，权威 finished 仍可能被并发 mark_lost/dispatch timeout 覆盖。
  - 详情:定位：WP-C `services/outcomes.py` 的锁序声明、`redis/reconcile.py` 改动范围及 TC-20d/TC-21。方案只明确记录器锁 task/log_file/schedule、`events._update_task` 锁 task，却未要求 `reconcile.mark_lost`、dispatcher 超时、maintenance 标 lost 等写入者锁 Task/Execution；现有 reconcile 会先无锁选出 active Execution。可发生 EventConsumer 提交 finished 后，reconcile 持有的陈旧对象再提交 lost，Task 因已是 complete 不再 rollup，随后记录器按 lost 计错并可能禁用调度。需为所有 Execution/Task 终态写入定义一致的行锁或条件更新协议及完整锁序，并增加 finished 与 `mark_lost`、dispatch-timeout 并发交错的 PostgreSQL 测试。
- [major] R-03 旧命令流清理条件排除了仍保留在 nodes 表中的退役节点，无法兑现 G1。
  - 详情:定位：WP-A `delete_stale_command_streams` 与 TC-16。现有节点删除是软删除，`nodes` 行会保留；更换 endpoint 后遗留的旧 agent 行也可能长期存在。因此“agent_id 不在 nodes 表”只覆盖纯孤儿键，退役但仍有历史行的旧 agent 命令流永远不会清理，TC-16 也刻意只测不存在的 ghost。应定义对软删除/明确退役且心跳陈旧节点的安全清理条件，并结合非终态任务和未决 outbox 做保护；测试应覆盖退役旧节点被删以及健康或可能回归的节点被保留。
- [major] R-04 测试未覆盖 Scrapy stats 从服务端事件入库到自动禁用的关键链路。
  - 详情:定位：TC-06、TC-06b、TC-18～TC-21。现有用例分别验证 agent 发出 stats、纯函数判错和失败任务计数；TC-06b 的服务端事件测试只明确覆盖 `log_bytes`/`log_flood`。若 `apply_event` 遗漏 `error_count` 或 `finish_reason` 入库，事故中的“scrapyd finished 但 ERROR>0”仍会被记为成功，而全部现有断言可通过。应增加正常 `attempt.finished` 事件携带 `error_count>0`/异常 `finish_reason`，经持久化、`record_task_outcomes`、账本重算直至自动禁用的集成用例，并覆盖正常 finished 清零分支。

## 总评
证据契约合规：测试表逐条声明为 A 档并给出文本证据形态，C 档为 0。方案对既有多项时序问题已有充分处理，但目录硬界的异常路径和终态写入并发协议仍不成立，且旧流清理与核心 stats 验收链路存在缺口，需修订后重评。

VERDICT: fail
