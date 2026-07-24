---
task: maintenance-resource-dashboard
round: 03
date: 2026-07-24
---

# 实现记录:第 03 轮(修复轮)

修复 review-round-02-fail 的 1 blocker + 1 major。R-02 是真实缺陷(1 行源码
修复 + 测试),R-01 是证据命令 + 一条缺失的零遍历断言。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/server/dopilot_server/api/v1/maintenance.py | **R-02 源码修复**:`resource_stats` 端点注入 `settings`,无快照分支返回真实 `settings.maintenance.enabled`(原写死 `True`,自动清扫关闭时会误报为开启) |
| apps/server/tests/test_resource_stats.py | 新增 `test_tc04_no_snapshot_reports_true_sweep_enabled`(enabled=false + 无快照 → `sweep_enabled:false`) |
| apps/agent/tests/test_heartbeat_worker.py | 新增 `test_build_request_reads_cache_never_walks_fs`:计数 stub 断言 `snapshot()` 恰调一次,并 monkeypatch `os.walk` 断言 build_request **零文件系统遍历**(R-01 要求的计数/零遍历断言) |
| evidence/tc09-10-agent-disk.txt | 重生成:CMD 头改为**真实**五个 pytest node id(2×TC-09 + 3×TC-10),`5 passed` |
| evidence/tc01-11-server-resource-stats.txt | 重生成(含新增 R-02 端点用例,`43 passed`) |
| evidence/tc15-pytest.txt、tc15-ruff.txt | 重生成(`618 passed` / clean) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | (a) `tc09-10-agent-disk.txt` 的 CMD 头此前用占位符 `<TC-09 x2> <TC-10 x2>`,已改为**逐字**的完整 pytest 命令(五个 node id),完整 stdout + `# Exit code: 0`。(b) plan TC-10 要求"用计数 stub 断言心跳路径未触发遍历"——第 01/02 轮的两个 disk 用例只核对载荷,未含该断言(记录确有夸大)。本轮新增 `test_build_request_reads_cache_never_walks_fs`:`CountingDisk.snapshot` 计数、`os.walk` 被 monkeypatch 计数;断言 `snapshot==1` 且 `walk==0`,如实证明 build_request 只读缓存、绝不采样/遍历。 |
| R-02 | major | 端点无快照分支原固定 `sweep_enabled=True`;当 `maintenance.enabled=false` 时与真实配置相反。改为 `Depends(get_settings)` 注入并返回 `settings.maintenance.enabled`。新增用例覆盖 enabled=false + 无快照组合(前端据此显示"自动清扫已关闭")。有快照分支不受影响(快照顶层已带真实 `sweep_enabled`,由 `collect_snapshot` 写入)。 |

## 测试结果

档位照抄 plan。全量 `618 passed, 1 skipped`(跳过项 TC-17 无
`DOPILOT_TEST_PG_URL` 时;真 PG 由 tc17 脚本补跑 pass)。仅列本轮受影响用例。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-04 | A | pass | tc01-11-server-resource-stats.txt(新增 `test_tc04_no_snapshot_reports_true_sweep_enabled` + 既有六节点/畸形/401/无快照零采样) |
| TC-10 | A | pass | tc09-10-agent-disk.txt(`5 passed`,新增 `test_build_request_reads_cache_never_walks_fs`:snapshot==1、os.walk==0) |
| TC-15 | A | pass | tc15-pytest.txt(`618 passed`)、tc15-ruff.txt(clean);web 侧沿用 round-01 tc15-web-*.txt(web 源码未动) |
| TC-17 | A | pass | tc17-postgres.txt(外层命令 + 完整输出 + `# Script exit code: 0`,源码/脚本未变) |
| TC-01..03,05..09,11..14,16 | A/B | pass | 沿用前轮证据(相应源码未变;server 全量已含其绿) |

## 与方案的偏差

- 无新增偏差(round-01 的 `DiskStatus` 独立模块、Progress 中性填充仍适用)。
- 记录准确性更正:第 01 轮记录曾把"零遍历断言"记为已覆盖,实际到本轮才补上
  该断言;此处如实说明。
