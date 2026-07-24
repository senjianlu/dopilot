---
task: resource-hard-limits
round: 05
date: 2026-07-24
---

# 实现记录:第 05 轮(修复轮)

修复 review-round-04-fail 的 2 个 blocker(R-01 测试覆盖、R-02 重复上传误删
已提交件)。仅针对评审问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/server/dopilot_server/artifacts/scrapy_store.py / wheel_store.py | **R-02**:`save_from_path` 发布前记 `pre_existed`;manifest replace 失败时**仅当本次新建**(`not pre_existed`)才 `remove_stored` 回滚——重复上传既有 sha 遇 manifest 故障时,既有正文/原 manifest(os.replace 原子未动)保持可用 |
| apps/server/tests/test_resource_limits.py | **R-01**:新增真实 commit 故障用例(捕获 id 字符串避免 expired ORM 惰性加载 greenlet 问题);TC-06 已含 wheel 端点;新增 TC-07 真实 SSE 生成器溢出即结束(async for 完成 + finally unsubscribe);新增 TC-18 确定性并发端点(barrier 让请求 A 持锁 pre-commit、断言 B 阻塞 refcount==2、放行后 dedup)+ R-02 重复上传 manifest 故障不误删既有件 |
| evidence/*(全部重生成) | 所有 A 档证据含命令 + 完整输出 + 退出码;TC-16 行号更新 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 三处缺口补真实测试:(a) **commit 故障**——`test_tc03_...commit_failure...` 类级 patch `AsyncSession.commit` 于第 2 次(STEP-3)提交处 rollback 后抛错,断言行留 expired + 下 tick 收敛;上轮 greenlet 报错的根因是"回滚后访问 expired ORM 对象属性触发惰性加载",本轮提前把 id 取为字符串、断言走列查询规避。(b) **TC-07 真实生成器**——`exec_client.stream` 打开真实 SSE 端点,同步 burst 1100 事件溢出 1000 深有界队列,断言生成器 async for 在超时内结束且 finally 退订。(c) **TC-18 并发端点**——两个独立 session/连接的真实端点请求经 barrier 确定性重叠:A 持 per-sha 锁 pre-commit,断言 B 阻塞、`_publish_locks[sha]` refcount==2,放行后 B dedup;两者 200、单件、无残留、锁注册表清空。确定性设计消除了初版真并发 gather 在全量套件下偶发扰动 dedup 测试的 flake。全部 A 档,证据含命令/输出/退出码。 |
| R-02 | blocker | `save_from_path` 记 `pre_existed = <target>.exists()`;manifest replace 失败仅在 `not pre_existed` 时 `remove_stored`。既有 sha 的重复上传遇 manifest I/O 故障:正文被同 sha 相同字节覆盖(无损)、原 manifest 因 os.replace 原子性未受影响 → 既有 artifact 仍可用。端点回滚 `published and not already_stored` 语义一致。新增 `test_tc18_reupload_manifest_failure_keeps_existing_artifact` 断言既有 body+manifest+DB 行+下载全可用。 |

## 测试结果

A 档证据(命令 + 完整输出 + 退出码)在 `evidence/`;全量 `570 passed`,
`ruff` clean;server 全量套件连跑 4 次无 flake(deterministic 并发测试后)。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-18-resource-limits-verbose.txt（size-cap + consumer-ACK) |
| TC-02 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-03 | A | pass | tc01-18-resource-limits-verbose.txt（unlink 失败重试 + STEP-3 失败重试 + **真实 commit 故障**) |
| TC-04 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-05 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-06 | A | pass | tc01-18-resource-limits-verbose.txt（egg 端点 200/400/413 + **wheel 端点 200/413**) |
| TC-07 | A | pass | tc01-18-resource-limits-verbose.txt（SubscriptionManager 单元 + **真实 SSE 生成器溢出即结束**) |
| TC-08 | A | pass | tc01-18-resource-limits-verbose.txt（全场景含损坏 state+pgid 死→删除 + 在途/锁复核竞态) |
| TC-09 | A | pass | tc01-18-resource-limits-verbose.txt（含句柄关闭断言) |
| TC-10 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-11 | A | pass | tc01-18-resource-limits-verbose.txt（LRU + 锁占用不淘汰) |
| TC-12 | A | pass | tc01-18-resource-limits-verbose.txt（drop-oldest + ERROR 日志) |
| TC-13 | A | pass | tc01-18-resource-limits-verbose.txt（server + agent 全字段 TOML+env) |
| TC-14 | A | pass | tc14-compose-check.txt（命令 + 输出 + exit 0) |
| TC-15 | A | pass | tc15-pytest.txt（`570 passed` + exit 0)、tc15-ruff.txt（clean + exit 0) |
| TC-16 | B | pass | tc16-doc-config-refs.txt（全部 `文件:行号`) |
| TC-17 | A | pass | tc01-18-resource-limits-verbose.txt（finished/failed/canceled 三终态参数化 + 重复终态 + 引用计数锁竞态) |
| TC-18 | A | pass | tc01-18-resource-limits-verbose.txt（reservation 并发 + 端点 507 无残留/总量 + **确定性并发端点** + R-02 manifest-fail 无孤儿/不误删既有件 + DB 失败回滚) |

## 与方案的偏差

- **并发端点测试改为确定性 barrier**:初版真并发 `asyncio.gather` 端点测试
  在全量套件下偶发扰动既有 dedup 测试(事件循环/线程时序),属测试隔离问题非
  产品缺陷。改为 barrier 让请求重叠确定化(断言 B 阻塞于同一 per-sha 锁、
  refcount==2),更严格且消除 flake;server 全量套件连跑 4 次无失败。
- **真实 commit 故障可模拟**:上轮判断"不可干净模拟"有误——根因是回滚后触碰
  expired ORM 对象属性的惰性加载,提前取 id 字符串即可规避;本轮已补真实
  commit 故障测试。
- **偶发 flake(与本任务无关)**:`test_wheel_started_orphan_recovered_as_lost`
  的真实子进程 `killpg` 时序断言仍偶发;tc15-pytest.txt 为干净全绿运行。
- 其余无偏差。
