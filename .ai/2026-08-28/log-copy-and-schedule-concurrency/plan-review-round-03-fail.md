# Plan 评审:第 03 轮

## 问题清单
- [plan-blocker] R-01 定长日志快照依赖“文件只增不减”，但现有维护流程会原地截断同一文件
  - 详情:plan.md:155-173、416-417 承诺 snapshot_size 字节必然读满，并称仓库不存在截断路径；实际 apps/server/dopilot_server/services/maintenance.py:337-350 会对已封存日志执行 fh.truncate。若下载在 fstat 后与该维护任务并发，已打开的同一 inode 仍会缩短，响应体将小于 Content-Length，直接违反方案的精确快照契约。须在方案阶段选择可保证一致性的机制（例如与截断流程建立读写协调、先物化独立快照，或取消固定长度承诺并重新定义响应语义），并新增并发截断的确定性 A 档用例。
- [major] R-02 TC-08 在现有 ASGI 测试栈中无法证明下载期间数据库连接已经释放
  - 详情:TC-08 计划通过 client.stream 打开未读完的响应后再发数据库请求，但仓库测试客户端使用 httpx.ASGITransport（apps/server/tests/conftest.py），该 transport 会先完整消费 ASGI 响应体，再把 Response 返回给 client.stream 上下文。因此第二个请求实际发生时下载已经结束，即使错误实现把 session 钉到流结束，该用例也会通过。应改为可控的异步屏障：后台启动下载请求，在 aiter_snapshot 已进入且被 asyncio.Event 阻塞时并发发起第二个请求，并用超时断言其完成；或使用真正支持增量响应的测试 harness。
- [major] R-03 测试仅验证 max_concurrency=0 能保存，没有验证其“不限并发”的核心行为
  - 详情:B1、ADR 与回滚策略都把 0 定义为恢复旧行为的逃生舱，但 TC-09 只断言 API 回显 0；将 0 错误实现为“零个任务可运行”或普通有限上限仍可能通过全部并发用例。应增加 A 档行为用例：在 max_concurrency=0 且已有 active task 时连续手动触发仍均成功；同时建议 TC-17 用 caplog 断言超限定时触发确实记录约定的服务端日志。

## 总评
证据表已逐条声明档位与证据形态，A/B/C 分配及 C 档比例合规，rawf 轮次和文档回写范围也与现有工作流一致。但日志快照契约与仓库既有截断机制发生架构冲突，且两个关键验收行为的测试目前可能误通过或未被覆盖，因此本轮必须 fail。

VERDICT: fail
