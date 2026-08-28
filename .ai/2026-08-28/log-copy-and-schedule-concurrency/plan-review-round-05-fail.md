# Plan 评审:第 05 轮

## 问题清单
- [plan-blocker] R-01 定时 coalesce 在行锁之前执行，竞态下会漏掉刚提交的未下发积压
  - 详情:plan.md:341-343 规定 fire_timer 先调用 has_undispatched_backlog_for_schedule，再获取 schedule 行锁；该查询只能看到已提交行。若 trigger-now 已持锁并正在建单，timer 会先查到“无积压”、随后等待行锁；前者提交 unresolved outbox 后，timer 获锁却不再检查积压，在 max_concurrency=0 或上限仍有余量时会继续建单，违反“既有 coalesce 行为不变”的方案边界。应改为先锁定并刷新 schedule，再按 enabled → backlog coalesce → concurrency 的顺序在同一串行区内判断；新增 PostgreSQL A 档竞态用例，以 max_concurrency=0 避免并发上限掩盖问题，验证先行事务提交 unresolved outbox 后，等待者必须跳过且不创建第二个任务。
- [major] R-02 前端测试完全 mock 了新增下载 API helper，无法证明真实请求参数和 Blob 配置正确
  - 详情:plan.md:236-239 要求 downloadTaskLog 将 executionId/stream 映射为后端 query 参数并设置 axios responseType="blob"，但 TC-24（plan.md:475）把该 helper 整体 mock 掉，只验证组件调用它。即使实现漏掉 responseType、使用错误的 execution_id 参数或未转发 stream，现有前后端用例仍会全部通过而真实 UI 下载失败或下载错日志。应增加 A 档 API 层用例，实际执行 downloadTaskLog 并断言 URL、execution_id、stream、responseType="blob" 及 Blob 返回值。
- [major] R-03 测试未覆盖下载文件描述符在正常结束和中途取消时的释放契约
  - 详情:plan.md:206-208 明确把生成器 finally 关闭 fh 作为防止 fd 泄漏的资源契约，但 TC-01～TC-09 均未断言文件对象已关闭；省略 finally 的实现仍可通过全部用例，重复下载或客户端断开后会逐步耗尽进程文件描述符。应增加 A 档确定性用例，分别在完整消费生成器以及读取首块后 aclose/取消时断言 fh.closed，覆盖正常与中断路径。
- [major] R-04 并发测试没有验证多 execution 的一个 task 只能占用一个额度
  - 详情:plan.md:268 将“按 task 计 1、不按 execution”定义为核心口径，但 TC-13～TC-19 没有构造一个 active task 扇出多个 execution 的场景；错误地 join/count execution 的实现仍可能通过。应增加 A 档行为用例：max_concurrency=2，已有一个带至少两个 execution 的 active task 时，下一次 trigger-now 仍应成功；由此约束 active 计数必须为 1。

## 总评
证据表已逐条声明档位与证据形态，31 个 A 档、2 个 B 档、0 个 C 档的分配合规，异常路径覆盖也较充分。但 coalesce 与新行锁的组合仍存在实际竞态，且下载传输链路、fd 生命周期和 task 计数粒度存在关键测试缺口，因此本轮按 plan-review 规则判定 fail。

VERDICT: fail
