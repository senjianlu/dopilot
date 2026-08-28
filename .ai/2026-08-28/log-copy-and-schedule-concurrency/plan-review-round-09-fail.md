# Plan 评审:第 09 轮

## 问题清单
- [major] R-01 aiter_snapshot 在异步打开文件期间被取消时仍可能泄漏文件描述符
  - 详情:定位：A1-b 的 fd 释放设计与 TC-34。方案要求磁盘操作经 asyncio.to_thread 下沉，因此 aiter_snapshot 首次迭代通常需执行 `fh = await asyncio.to_thread(open, ...)`；若客户端在该 await 期间断开，工作线程仍可能成功打开文件，但取消会阻止结果赋给 fh，后续 finally 无法关闭这个句柄。当前 TC-34 只覆盖未启动生成器、首块产出后 aclose 和 aprobe_snapshot 取消，均无法发现“生成器已启动、尚未完成 open”这一窗口。应设计取消安全的句柄移交/回收机制，或改用每次在线程内完成 open-read-close 的自闭环读取方式，并增加确定性用例：阻塞生成器内部 open、取消首个 __anext__、放行工作线程后断言 fd 回到基线。
- [major] R-02 LogViewer 用例未验证 stream 向下载 helper 的转发，可能下载与当前视图不同的日志
  - 详情:定位：A2 明确要求 `downloadTaskLog(taskId, {executionId, stream})`，但 TC-24 只断言 `(taskId, {executionId})`；TC-35 仅验证 helper 自身能够发送 stream，不能证明组件把其 `stream` prop 传入。实现若遗漏该参数，查看 err 等非默认流时仍会下载默认 log，且现有全部用例可通过。应让 TC-24 以 `stream="err"` 渲染 LogViewer，并断言 helper 收到 `{executionId, stream: "err"}`。

## 总评
调度行锁、事务边界、证据档位及 C 档比例总体自洽，rawf 工作流约定也已满足。当前仍有一个真实的 fd 取消泄漏窗口和一个会让错误日志下载实现全绿的验收覆盖缺口，因此按 plan-review 规则判定 fail。

VERDICT: fail
