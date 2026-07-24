---
task: maintenance-resource-dashboard
round: 05
date: 2026-07-24
---

# 实现记录:第 05 轮(修复轮)

修复 review-round-04-fail 的唯一 blocker(R-01):agent 侧磁盘采集 helper 把
目录访问失败伪装成零值——server 侧同类缺陷已在 round-04 修,本轮对 agent 侧
做对称修复。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/agent/dopilot_agent/janitor.py | 新增 `_dir_bytes`(采样专用:目录不存在→0,存在但不可读经 `os.walk(onerror=_raise)` / `os.stat` 传播异常→由 `_guard` 置 null;文件中途消失 benign 跳过);`_count_dirs`/`_count_glob` 改为"不存在→0,不可读→传播";`_collect_disk_sample` 的 workspaces/cache/scrapyd/outbox 字节改用 `_dir_bytes`。**缓存淘汰的 `_tree_size` 保持不变**(它需容错以免淘汰停滞) |
| apps/agent/tests/test_resource_limits.py | 新增 `test_tc09_dir_bytes_missing_vs_access_failure`(缺失→0、不可读→PermissionError 传播)与 `test_tc09_janitor_disk_sample_unreadable_dir_nulled`(真实遍历路径:scrapyd 不可读→`sample["scrapyd"] is None` 而非假 0,workspaces 仍有值) |
| evidence/tc09-10-agent-disk.txt、tc15-pytest.txt、tc15-ruff.txt | 重生成(agent disk `7 passed`、全量 `625 passed`) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | agent 磁盘采集 helper 原 `_tree_size`/`_count_dirs`/`_count_glob` 把 `OSError` 吞成 0,scrapyd/workspace/outbox 不可读时会生成"正常零值",违反 plan"子项不可读→置 null"。修复:采样路径改用**区分语义**的 `_dir_bytes`(缺失=0 合法、访问失败=传播→`_guard` 置 null)与"不存在→0、不可读→传播"的计数 helper;缓存淘汰仍用容错 `_tree_size`(职责不同,不能因一次读失败停摆)。新增 A 档用例**实际执行目录遍历访问失败路径**:①helper 级(缺失/不可读);②sweep 级(scrapyd 遍历 onerror 触发 PermissionError → 该子项 null、其余子项完好)。tc09-10 证据现 `7 passed`(2 采样 + 1 helper + 1 不可读遍历 + 3 TC-10),含真实命令 + 输出 + 退出码。 |

## 测试结果

全量 `625 passed, 1 skipped`(TC-17 无 env 跳过,真 PG 由 tc17 脚本 pass)。
仅列本轮受影响用例。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-09 | A | pass | tc09-10-agent-disk.txt(采样匹配已知树 + `_volume` 抛错 null + **`_dir_bytes` 缺失/不可读语义** + **scrapyd 不可读遍历→子项 null**) |
| TC-10 | A | pass | tc09-10-agent-disk.txt(3 心跳用例,含零遍历断言) |
| TC-15 | A | pass | tc15-pytest.txt(`625 passed`)、tc15-ruff.txt(clean);web 侧沿用 round-04 tc15-web-test.txt(`88 passed`,web 源码未变) |
| TC-17 | A | pass | tc17-postgres.txt(源码/脚本未变) |
| TC-01..08,11..14,16 | A/B | pass | 沿用前轮证据(相应源码未变) |

## 与方案的偏差

- 无新增偏差。`_dir_bytes` 与 `_tree_size` 并存是刻意区分:采样要如实反映
  访问失败(可观测性),淘汰要容错(不因读失败停摆)——与 plan 意图一致。
