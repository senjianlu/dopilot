# 评审:第 03 轮

## 问题清单
- [blocker] R-01 A 档记录仍将未完整覆盖的 plan 用例报告为全部通过，构成测试结果虚报
  - 详情:apps/server/tests/test_resource_limits.py:290、apps/agent/tests/test_resource_limits.py:85、415 / TC-03 名为 commit-fault 的测试实际在 304-309 行注入 SQL 构造失败，没有注入 commit 故障；TC-06 仅覆盖 egg endpoint，未覆盖 plan 要求的 wheel endpoint；TC-08 缺少“损坏 state + pgid 已死 + 静默期已满并被删除”；TC-09 未断言 drain 后文件句柄关闭；TC-12 未断言 ERROR 日志；TC-17 仅手工构造 finished state，未驱动 finished/failed/canceled 三种终态及重复终态；TC-18 的并发仅测试 reserve_quota，未并发驱动 endpoint；TC-13 也未覆盖全部新增字段的 TOML 与 env 双通道。implementation-round-03.md 却将这些用例完整记为 pass，与测试源码证据矛盾。需补交 TC-03、TC-06、TC-08、TC-09、TC-12、TC-13、TC-17、TC-18 上述缺失场景的测试实现，并为每个用例补交包含执行命令、完整 stdout/stderr 和退出码的 A 档原始证据。
- [major] R-02 Artifact manifest 发布失败时仍会留下未计入数据库配额的正文
  - 详情:apps/server/dopilot_server/artifacts/scrapy_store.py:239、246-248，apps/server/dopilot_server/api/v1/artifacts.py:141-163；wheel_store.py 与 wheel endpoint 存在同样问题。save_from_path 先 replace 正文、再 replace manifest；若第二次 replace 失败，函数未返回，endpoint 的 published 仍为 False，因此不会调用 remove_stored，正文和 manifest 临时文件均可残留，上一轮 R-04 未完全修复。应让 store 在发布任一步失败时自行回滚所有本次产物，或返回可判定的发布状态，并补充正文 replace 成功、manifest replace 失败的故障注入测试。
- [major] R-03 同一 SHA 的并发上传失败回滚可能删除另一请求已成功提交的 artifact
  - 详情:apps/server/dopilot_server/api/v1/artifacts.py:134-163、212-239 / 两个并发同内容请求都可能在正文存在前读到 already_stored=False，随后相互 replace 同一路径；其中一个 DB 提交失败后会 remove_stored，可能删除另一个请求已经成功提交并被数据库引用的正文和 manifest。应在按 SHA 串行化的临界区内完成存在性检查、发布与数据库结果协调，或使用明确的文件所有权/原子 create 语义，确保失败请求只回滚自己创建且尚未被其他成功事务采用的文件，并增加相同 SHA 并发成功/失败交错测试。

## 总评
上一轮的引用计数执行锁与缓存淘汰锁修复从代码上已基本到位，B 档引用也存在并支持结论。但 A 档覆盖仍与“全部通过”的实现记录矛盾，且 artifact 发布失败和同 SHA 并发回滚仍破坏聚合硬上限及已提交数据，因此本轮必须判定 fail。

VERDICT: fail
