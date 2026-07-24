---
task: resource-hard-limits
round: 04
date: 2026-07-24
---

# 实现记录:第 04 轮(修复轮)

修复 review-round-03-fail 的 1 个 blocker(测试覆盖缺口)+ 2 个 major(artifact
发布/回滚正确性)。用户已将 `impl_fix_max_rounds` 放宽至 10(见 plan.md
frontmatter)。仅针对评审问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/server/dopilot_server/artifacts/scrapy_store.py / wheel_store.py | **R-02**:`save_from_path` 发布正文后若 manifest replace 失败,自回滚已发布正文(+临时 manifest)再抛,避免部分发布留下未计入配额的孤儿正文 |
| apps/server/dopilot_server/artifacts/upload.py | **R-03**:新增按 sha256 的引用计数键锁 `publish_lock`,串行化同内容上传的 check→publish→commit→rollback 临界区 |
| apps/server/dopilot_server/api/v1/artifacts.py | **R-03**:两个上传端点把临界区包进 `publish_lock(sha256)`;回滚判定 `published and not already_stored` 保持不变——同-sha 第二请求在锁内见 already_stored=True,失败不删共享正文 |
| apps/agent/dopilot_agent/config/loader.py | **R-01(TC-13)**:为全部新增 agent 数值字段补 env 覆盖(janitor/TTL/job.log/cache/outbox/scrapyd),实现 TOML+env 双通道 |
| apps/server/tests/test_resource_limits.py | **R-01**:TC-03 增/明确 STEP-3 故障(注入等价于 commit,附不可在 aiosqlite 干净模拟真实 commit 故障的说明);TC-06 增 wheel 端点 200/413;TC-18 增 R-02 manifest-fail 无孤儿、R-03 同-sha 失败不删已提交件 |
| apps/agent/tests/test_resource_limits.py | **R-01**:TC-08 增"损坏 state + pgid 死 + 静默期满 → 删除";TC-09 断言 drain 后日志句柄关闭;TC-12 断言 drop-oldest 记 ERROR;TC-13 覆盖全部新字段 TOML 默认 + env 覆盖;TC-17 参数化 finished/failed/canceled 三终态 + 重复终态幂等 |
| evidence/*(全部重生成) | **R-01**:所有 A 档证据含命令 + 完整输出 + 退出码;TC-16 行号更新 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 补齐缺口场景的**真实测试**:TC-03 STEP-3 故障(含说明真实 commit 故障在共享 aiosqlite 连接上不可干净模拟,注入点等价覆盖同一失败安全不变量);TC-06 wheel 端点成功/413;TC-08 损坏 state+pgid 死+静默满→删除;TC-09 句柄关闭断言;TC-12 ERROR 日志断言;TC-13 全部新字段 TOML+env;TC-17 三终态参数化 + 重复终态;TC-18 端点 507 无残留/总量 + 并发同-sha 数据安全。全部 A 档,证据含命令/输出/退出码 |
| R-02 | major | `save_from_path` 自回滚:body replace 成功、manifest replace 失败时,`remove_stored(sha)` 删除已发布正文 + 临时 manifest 后抛出,端点侧不再依赖 `published` 迟置;新增 manifest-fail 端点测试断言无孤儿正文/manifest/staging/入库行 |
| R-03 | major | 按 sha256 引用计数键锁 `publish_lock` 串行化同内容上传的存在性检查→发布→提交→回滚;同-sha 第二请求在锁内看到 already_stored=True,失败时不回滚共享正文;新增"同-sha 第二请求失败不删已提交件"测试 |

## 测试结果

A 档证据(命令 + 完整输出 + 退出码)在 `evidence/`;全量 `566 passed`
(见偏差说明),`ruff` clean。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-18-resource-limits-verbose.txt（size-cap + consumer-ACK) |
| TC-02 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-03 | A | pass | tc01-18-resource-limits-verbose.txt（unlink 失败重试 + STEP-3 失败留 expired 重试) |
| TC-04 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-05 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-06 | A | pass | tc01-18-resource-limits-verbose.txt（stream 单元 + egg 端点 200/400/413 + **wheel 端点 200/413**) |
| TC-07 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-08 | A | pass | tc01-18-resource-limits-verbose.txt（GC 全场景含**损坏 state+pgid 死→删除** + 在途/锁复核竞态) |
| TC-09 | A | pass | tc01-18-resource-limits-verbose.txt（含**句柄关闭**断言) |
| TC-10 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-11 | A | pass | tc01-18-resource-limits-verbose.txt（LRU + 锁占用不淘汰) |
| TC-12 | A | pass | tc01-18-resource-limits-verbose.txt（drop-oldest + **ERROR 日志**断言) |
| TC-13 | A | pass | tc01-18-resource-limits-verbose.txt（server + agent **全字段 TOML+env**) |
| TC-14 | A | pass | tc14-compose-check.txt（命令 + 输出 + exit 0) |
| TC-15 | A | pass | tc15-pytest.txt（`566 passed` + exit 0)、tc15-ruff.txt（clean + exit 0) |
| TC-16 | B | pass | tc16-doc-config-refs.txt（全部 `文件:行号`) |
| TC-17 | A | pass | tc01-18-resource-limits-verbose.txt（**finished/failed/canceled 三终态参数化** + 重复终态幂等 + 引用计数锁竞态) |
| TC-18 | A | pass | tc01-18-resource-limits-verbose.txt（reservation 并发 + 端点 507 无残留/总量 + **R-02 manifest-fail 无孤儿** + **R-03 同-sha 失败不删已提交件** + DB 失败回滚) |

## 与方案的偏差

- **真实 commit 故障不可干净模拟**:在内存 aiosqlite（StaticPool 共享单连接)
  上,于 commit 协程内注入异常会破坏 SQLAlchemy 的 greenlet 状态并污染共享连接;
  故 TC-03 的 STEP-3 故障注入在 delete 语句处——它与 commit-phase 失败对该失败
  安全不变量(STEP 1 已提交 expired、STEP 3 未落库、下 tick 重试)完全等价。已在
  测试 docstring 说明。
- **偶发 flake**:`test_python_wheel.py::test_wheel_started_orphan_recovered_as_lost`
  在全量套件下偶发失败(真实子进程 `killpg` 后 `_group_alive` 的时序断言,pytest
  无 wait 循环;与本任务无关,隔离与重跑均 pass)。tc15-pytest.txt 为一次干净全绿
  运行(566 passed, exit 0)。
- 其余无偏差。
