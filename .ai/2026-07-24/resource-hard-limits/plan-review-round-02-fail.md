# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 agent 孤儿判定把所有 state 文件误当作运行时活跃集，损坏 state 将永久无法回收，且 job.pgid 的写入顺序不可实现
  - 详情:定位：Phase C/C1 与“实现方案”第 5 点。`StateStore.list_execution_ids()` 实际只枚举 `state/executions/*.json` 文件名（`apps/agent/dopilot_agent/state/store.py:236`），不区分运行态、终态或文件是否可读；因此损坏 state 文件对应的 execution 仍在该集合中，“不在活跃集”条件永远不成立，TC-08 所要求的损坏 state 安全判定也无法通过。另方案写明“写 job.pgid → 起子进程”，但 pgid 只能在 `create_subprocess_exec` 成功后取得。应重新定义真正的内存运行集合与持久 state 的关系，并将顺序改为先 spawn、取得 pgid、原子写 sidecar，再启动 drain；同时明确 spawn 成功但 sidecar 写入失败时的终止/回收策略，并在 TC-08 增加损坏 state 且 pgid 已死、静默期已满后确实被删除的断言。
- [major] R-02 SSE 队列满时仅从注册表移除订阅者不能真正断开流，测试也未覆盖生成器退出
  - 详情:定位：B6、TC-07；现有生成器阻塞于 `queue.get()`（`apps/server/dopilot_server/api/v1/tasks.py:382`），只把队列从 `SubscriptionManager._subs` 移除不会唤醒或终止生成器；队列已满时又无法直接塞入 CLOSE。结果是慢订阅者仍可能存活到 30 分钟生命周期或客户端主动断开，未实现“满则断开”的资源治理目标。TC-07 只断言从注册表移除，可能让该缺陷通过。方案须规定可执行的关闭机制（如丢弃/清空后放入 CLOSE，或显式取消订阅任务），并测试 StreamingResponse 生成器及时结束、finally 清理完成以及后续 publish/close 不抛错。
- [major] R-03 自动保留直接复用先删磁盘再提交数据库的清理函数，异常时会留下数据库索引指向已删除日志且测试未覆盖
  - 详情:定位：B2、TC-03。现有 `cleanup_terminal_data` 先 unlink 日志正文（`apps/server/dopilot_server/services/maintenance.py:133`），随后才删除数据库行，且由调用者提交；若数据库删除或 commit 失败，事务回滚后日志索引仍在而正文已不可恢复。把该路径改为自动周期执行会放大该一致性风险，并违背日志缺口/截断应成为可见审计事实的既有不变量。方案应设计失败安全的清理顺序或可恢复/可审计的两阶段语义，并在 TC-03 注入 unlink、SQL 和 commit 异常，验证不会产生未标记的悬空索引且下一 tick 可安全重试。

## 总评
证据契约本身合规：17 条用例均逐条声明档位与证据形态，C 档为 0，也没有把可自动化用例降档。当前主要问题集中在 agent 孤儿安全判定、SSE 真正断流和自动清理的一致性异常路径；这些会直接削弱本任务的资源治理目标并造成实现返工，因此本轮 fail。

VERDICT: fail
