# Plan 评审:第 08 轮

## 问题清单
- [plan-blocker] R-01 LogsDirGauge 的校准算法在并发删除或截断时会低估目录大小，无法保证总预算硬界。
  - 详情:定位：plan.md:67-68、90、TC-11b。`value = walk_total + (delta_counter - mark)`只对并发新增保持保守；若 walk 已看到删除后的目录状态，同时 `delta_counter` 又记录 `sub(-n)`，同一删除会被扣两次，产生低估并允许后续写入突破 `max_total_bytes`。此外，`reserve()`已增加 value，plan.md:90 又要求成功落盘后 `add(written)`，预留与提交语义也相互矛盾。应重新定义不会低估的校准/预留协议，例如串行化校准与删除、或在校准期间对负增量采取保守合并，并补充 barrier 控制的并发删除/截断测试；同时明确 reserve、commit、release 各自是否改变计数。
- [plan-blocker] R-02 两阶段日志清理与仅拒收 complete 状态的设计仍允许晚到日志在删除期间重建孤儿文件。
  - 详情:定位：plan.md:67、90、TC-13b。既有 `cleanup_terminal_data` 会先把日志行改成 `expired` 并提交，再解除行锁后 unlink 正文；方案只规定 `status == complete` 时拒收增量。晚到的 LogConsumer 因而可在 expired 提交后取得锁并继续 append，甚至在 unlink 后重建同路径文件，造成 DB 行已删除但正文残留、目录预算失真。应把 expired 等所有非可写状态纳入封口拒收契约（例如仅 active/finalizing 可写），并增加“expired 已提交、unlink 尚未完成时到达日志增量”的 PostgreSQL 并发测试。
- [plan-blocker] R-03 给受管 scrapyd 守护进程注入日志上限环境变量会让 .pth 钩子错误作用于守护进程自身。
  - 详情:定位：plan.md:80、82、TC-01f。`.pth` 会在 scrapyd 守护进程解释器启动时导入 `logcap`，而 `ScrapydProcess.start()` 又给该进程设置 `DOPILOT_JOB_LOG_CAP_BYTES`；因此守护进程创建的任何 `logging.FileHandler` 都会被限流并在达限时向守护进程发送 SIGTERM，可能同时中断全部 crawler，与“非 scrapy 进程不受影响”及作业隔离目标冲突。应仅依据 crawler 的 `-s`/`_job` argv 激活钩子，或增加可证明的 crawler 身份与目标 job.log 校验，不能把激活环境变量直接设置给 scrapyd daemon；测试还需证明 daemon 的 FileHandler 不会触发自杀。
- [plan-blocker] R-04 outcome_reset_at 依赖可变的 finished_at，不能阻止重启用前的 soft-lost 任务在纠正后跨越重置边界。
  - 详情:定位：plan.md:106、108、120、TC-23。方案明确不改现有 `_update_task` rollup，而现有 `events.py` 在 lost 被权威终态覆盖时会把 `Task.finished_at` 重写为纠正发生的当前时间。若调度已在两者之间重新启用，该旧任务补记/更新账本时的 finished_at 将晚于 `outcome_reset_at`，仍会被当作重置后的结果计数，TC-23(b)假定其保持在水位线之前并不成立。应使用不会被晚到终态改写的持久 generation/reset epoch（最好在任务创建时固化），或另行保存稳定的结果归属时间，并覆盖“重置前尚未入账的 lost 在重置后被纠正”的测试。
- [major] R-05 通知唯一键未包含 type，同一执行的 log_flood 与 log_truncated 会互相覆盖。
  - 详情:定位：plan.md:90、92、103-104、190-193。两类通知都以裸 `execution_id` 作为 dedupe_key，而部分唯一索引仅覆盖 `dedupe_key`；洪泛执行通常同时产生 `log_truncated` 和 `log_flood`，后写入者会命中前一类型的行并只更新 payload/severity/count，留下与 payload 不匹配的旧 type，导致消息缺失或前端错误渲染。应将唯一约束改为 `(type, dedupe_key)`，或对键做类型命名空间，并增加同一 execution 同时产生两类通知且各自独立去重的测试。

## 总评
证据契约合规：测试表逐条声明了 A 档和命令型证据形态，C 档为 0。方案仍有目录硬界、日志删除并发、scrapyd 进程隔离及重置水位线方面的架构错误，因此本轮必须 fail。

VERDICT: fail
