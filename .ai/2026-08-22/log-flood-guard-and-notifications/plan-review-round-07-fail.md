# Plan 评审:第 07 轮

## 问题清单
- [plan-blocker] R-01 手动重新启用只清零 Schedule 字段却不建立账本重置边界，旧失败会在下次重算时立即恢复。
  - 详情:定位：plan.md:102、106、108、178 及 TC-23。`consecutive_error_count` 每次都从 `schedule_outcome_ledger` 的最新连续失败前缀重算，而 `update_schedule(enabled=true)` 仅清除 Schedule 上的计数和 `auto_disabled_*`；下一次新结果或旧 lost 任务纠正入账时，禁用前的失败仍在账本头部，会被重新计入并可能只经一次新失败就再次禁用。需设计持久的重置边界（如 generation/reset watermark 或账本 reset 记录），并覆盖“重新启用后一次失败从 1 开始”和“重新启用后旧任务迟到纠正不跨越重置边界”的测试。
- [plan-blocker] R-02 LogsDirGauge 的异步全量 reset 会与日志写入并发丢失增量，无法兑现目录预算硬界。
  - 详情:定位：plan.md:67-70、90、145-148。方案让 retention 在线程池执行 `os.walk` 后 `reset(total)`，同时 LogConsumer 可继续落盘并 `add(written)`；若 walk 在写入前取样、reset 在 add 后执行，新增字节会从 gauge 消失，反向时还会重复计数。出现低估后，准入检查可继续写入并突破 `max_total_bytes`。需规定校准与预留/写入/删除之间可证明正确的同步或带版本增量合并机制，并增加 barrier 控制的“校准与临界预算写入并发”测试，断言实测目录大小始终不越界。
- [plan-blocker] R-03 定期截断和预算淘汰引入了未经协调的第二个日志文件写入者，违反现有单写者不变量。
  - 详情:定位：plan.md:67、69、90、TC-13～TC-15；现有 `apps/server/dopilot_server/logs/files.py:180-185` 明确要求除串行 LogConsumer 外不得并发修改正文。Task 进入 terminal 后，其日志仍可能在 drain 窗口内保持 active/finalizing；maintenance 此时可 truncate 或经 `cleanup_terminal_data` 标记、unlink，而 LogConsumer 已加载旧状态并正在 append，可能造成偏移重叠、截断后重写、删除后重建孤儿文件或 DB/物理大小失配。需把 eligibility 收紧到已封口日志，并为消费、截断、删除建立统一的每日志锁或数据库原子 claim；测试须覆盖晚到增量与 truncate/evict 的真实并发交错。
- [plan-blocker] R-04 结果记录器的“同事务封口”未与独立事件和日志消费者串行化，仍可能永久记录错误结果。
  - 详情:定位：plan.md:106-107、165-175、TC-20b/TC-21。ReconcileLoop、EventConsumer、LogConsumer 使用独立 session；只对 Schedule `FOR UPDATE` 不能保护 Task 与 ExecutionLogFile。日志消费者可在封口提交前读到 active、写入截断内容并稍后提交，而记录器已按旧完整性记录成功；同理，lost→finished 事件若在 lost 结果事务提交前读取 Task，看不到 `outcome_recorded_at`，便不会清空它，最终可能留下 finished Task 对应 erroneous 账本。现有测试均为顺序调用，无法捕获这些竞态。需定义跨三个路径一致的行锁顺序、条件更新或应用级锁，并增加两个独立 session、barrier 控制的封口/晚到日志及 lost 覆盖并发测试。

## 总评
证据契约合规：测试表逐条声明了 A 档和证据形态，C 档为 0，异常路径覆盖也较丰富。但目录硬界、日志文件生命周期及结果账本在真实并发和人工重启用场景下仍不自洽，会造成越界、文件状态失真或错误自动禁用，方案需修订后重评。

VERDICT: fail
