# Plan 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 运行中日志的“前缀快照”语义与无界读到 EOF、起始 Content-Length 的方案互相矛盾
  - 详情:plan.md A1 同时要求运行中文件下载为下载开始时的前缀快照、响应携带开始时已知的 Content-Length、aiter_chunks 持续逐块读至 EOF。文件在下载期间继续追加时，无界读取可能返回起始大小之后的字节，造成响应体超过 Content-Length，也不再是开始时快照。须明确先取得固定 snapshot_size，并让迭代器最多读取该字节数（同时处理读取期间文件缩短或消失），或取消快照与 Content-Length 承诺并定义另一套一致语义；还应增加运行中并发追加的自动化用例。
- [major] R-02 A 档证据契约未逐条声明完整证据形态
  - 详情:测试表 TC-02～TC-18 的“证据形态”多数仅写“pytest 输出”或“vitest 输出”，没有逐条声明 A 档强制要求的执行命令、完整 stdout/stderr 与退出码；只有 TC-01、TC-19 写全。review-standards.md 要求证据形态在 plan 阶段逐条定约。请逐条补成“命令 + 完整 stdout/stderr + 退出码”；可以明确引用同一份合并证据文件及其中对应命令或用例锚点。
- [major] R-03 日志下载异常测试没有覆盖方案承诺的磁盘文件缺失路径
  - 详情:A1 明确规定“无 log_file 行或磁盘文件不存在”均返回结构化 404，但 TC-03 只构造“无 log_file 行”。磁盘文件被 retention 删除、索引仍在或文件异常丢失时，StreamingResponse 生成器若在响应开始后才打开文件，可能变成 200 后流式异常，现有用例无法发现。请新增 A 档用例：保留 execution_log_files 行但删除 storage_path，断言请求在发送响应头前返回 404 的完整 envelope；方案也应明确在构造 StreamingResponse 前异步完成存在性或可打开性预检。
- [major] R-04 剪贴板不可用或写入拒绝的既定异常行为没有测试覆盖
  - 详情:A2 和风险表都承诺 navigator.clipboard 缺失或 writeText 拒绝时弹 error toast，但 TC-13 仅测成功、TC-14 仅测空缓冲 disabled；这是方案明确识别的非安全上下文边界，现有用例无法防止调用 undefined、未处理 Promise 或无提示失败。请增加 A 档 vitest，至少覆盖 clipboard 不存在或 writeText reject，并断言 error toast 且组件不崩溃。

## 总评
方案的并发闸主路径与 PostgreSQL 竞态验证总体自洽，档位分配也没有把可自动化项降到 C 档。当前仍有一处下载协议层自相矛盾，以及证据契约和两个已承诺异常路径的测试缺口；按 plan-review 规则应 fail，修订后再进入确认闸。

VERDICT: fail
