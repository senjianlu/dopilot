# Plan 评审:第 08 轮

## 问题清单
- [major] R-01 下载文件描述符的释放方案遗漏响应体尚未开始迭代及异步打开被取消的路径，仍可能泄漏 fd
  - 详情:定位：plan.md:145、160-162、206-208、TC-34（plan.md:559）。方案在返回 StreamingResponse 前通过 aopen_snapshot 在线程池打开 fh，却仅依赖 aiter_snapshot 的 finally 关闭；Python 异步生成器若在第一次 __anext__ 前被关闭，不会进入函数体及 finally，因此客户端在首块产生前断开、响应被中止或构造后未消费时 fh 不会关闭。此外，取消等待 asyncio.to_thread(open_snapshot) 不会停止工作线程，打开成功后的 fh 可能因结果无人接收而泄漏。TC-34 只覆盖完整消费和读取首块后的 aclose，无法发现这两个窗口。应在方案中定义独立于生成器是否启动的幂等资源所有权/兜底清理（如响应 background cleanup，并让 aopen_snapshot 在取消时等待底层打开结束后关闭所得 fh），并增加“首个 anext 前放弃响应”和“打开操作进行中取消”的确定性 A 档用例。

## 总评
调度并发闸、PostgreSQL 串行化、异常路径及证据档位整体已较完整，37 个 A 档、2 个 B 档、0 个 C 档符合证据契约。当前仍有一个可由客户端提前断开触发的 fd 泄漏窗口，且现有测试无法检出，按 plan-review 规则判定 fail。

VERDICT: fail
