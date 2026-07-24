# Plan 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 C2 未设计可行的持续排空机制，无法在限制 job.log 后保证子进程继续运行
  - 详情:定位：Phase C/C2、实现方案及 TC-09；现有 `apps/agent/dopilot_agent/runners/python_wheel.py:145-169` 将子进程 stdout/stderr 直接绑定到普通文件描述符，写入发生在子进程中，Python runner 无法在达到上限后截断该描述符的后续写入。若改为停止读取 PIPE，持续输出的子进程又会因管道填满而阻塞，与“进程继续运行、状态不受影响”冲突。方案须明确改为 `stdout=PIPE` 并设置持续 drain 的异步任务（仅在限额内落盘、越界写一次标记、之后丢弃但继续排空），同时定义 drain/reaper/terminate/aclose 的生命周期、异常处理和簿记清理；TC-09 还应以远超管道容量的输出验证进程不会阻塞。
- [plan-blocker] R-02 B5 的临时文件方案未覆盖现有内存型校验/存储接口，不能实现所声明的上传内存有界目标
  - 详情:定位：Phase B/B5、实现方案第 4 点、TC-06；两个 endpoint 当前最终调用 `ScrapyArtifactStore.save` / `WheelArtifactStore.save`，而 `apps/server/dopilot_server/artifacts/scrapy_store.py:75-146` 与 `wheel_store.py:60-134` 均要求完整 `bytes`，并通过 `BytesIO(content)` 校验后再次写盘。仅把 endpoint 改成分块临时文件，要么无法调用现有接口，要么仍需把最多 200MB 全量读回内存且重复落盘；方案也未说明同步 zip/hash/文件操作如何按项目异步边界移出事件循环。应在 plan 中明确新增基于路径/流的 store 接口：流式计算 hash、直接对临时文件执行 ZipFile 校验和元数据解析、在线程中完成阻塞文件操作、原子发布正文与 manifest，并完整清理所有失败路径。TC-06 应增加断言读取始终按限定 chunk 进行，避免实现回退为全量 `read()` 仍能通过。
- [major] R-03 C1 将“无可读 state”直接视为孤儿会误删仍在运行的 wheel 执行，且 TC-08 未覆盖该边界
  - 详情:定位：实现方案第 5 点及 TC-08；`StateStore.read()` 在 state 文件缺失、I/O 错误、JSON 损坏或模型校验失败时都会返回 `None`（`apps/agent/dopilot_agent/state/store.py:190-211`）。因此按 plan 把无 state 的旧 workspace 一律视为孤儿，可能在 state 损坏/丢失但子进程仍存活时删除其 workspace 和 job.log，违背“运行中执行永不删除”。同一把进程内 per-execution 锁不能证明跨重启遗留进程已经结束。方案须规定孤儿删除前的进程存活/所有权判定，或采用可证明安全的隔离与宽限策略；TC-08 应加入“缺失或损坏 state、但对应 pid/pgid 仍存活”的异常路径并断言不删除。
- [major] R-04 核心增长面 C6 没有对应测试，TC-15 全量回归不能证明终态簿记确实释放
  - 详情:定位：Phase C/C6 与测试用例表；方案要求释放 `CommandConsumer._locks`、`_inproc_wheel`、`LogPublisher._eof_sent` 及 runner 的多个 dict/set，但 TC-01～TC-14 没有任何用例验证这些容器在正常完成、失败、取消以及 EOF 发布后的清理时机。TC-15 仅运行既有全量测试，不能作为新增行为的针对性覆盖。应新增 A 档用例，至少覆盖 finished/failed/canceled、EOF 尚未发布时不得提前清理、EOF 后全部相关簿记移除，并验证重复终态/cleanup 不抛错。

## 总评
方案的证据契约形式合规：所有用例均逐条声明档位和证据形态，C 档为 0。当前仍有两处关键机制在既有 I/O 架构下不可按方案直接实现，并且 janitor 安全边界与内存簿记清理测试存在实质缺口，需修订 plan 后重评。

VERDICT: fail
