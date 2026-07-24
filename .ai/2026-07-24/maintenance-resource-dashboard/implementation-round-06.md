---
task: maintenance-resource-dashboard
round: 06
date: 2026-07-24
---

# 实现记录:第 06 轮(修复轮)

修复 review-round-05-fail 的 1 blocker(R-01 计数 helper 仍会把部分访问失败
当成 0)+ 1 major(R-02 缓存淘汰后样本仍报旧总量)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/agent/dopilot_agent/janitor.py | **R-01**:`_dir_bytes`/`_count_dirs`/`_count_glob` 改为**仅 `FileNotFoundError` 视作不存在(→0)**,`PermissionError` 等一律传播;弃用会把权限错误吞成 False-absent 的 `Path.exists()`/`Path.glob()`,计数改走 `os.scandir` + `fnmatch`(不吞扫描错误)。**R-02**:`_sweep_cache` 在淘汰循环后把最终 `total` 写回 `self._last_cache_bytes`,使同轮磁盘样本反映淘汰后的实际用量(原只在淘汰前写一次,样本会报旧的超限值一个周期) |
| apps/agent/tests/test_resource_limits.py | 新增 `test_tc09_count_helpers_missing_vs_access_failure`(count helper:匹配计数、缺失→0、scandir PermissionError→传播);新增 `test_tc09_cache_sample_reflects_post_eviction_size`(超限缓存淘汰后 `sample["cache"]["bytes"]` == 剩余实际 100、被淘汰目录确已删) |
| evidence/tc09-10-agent-disk.txt、tc15-pytest.txt、tc15-ruff.txt | 重生成(agent disk `10 passed`、全量 `627 passed`) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 上轮 helper 用 `Path.exists()` 门控(权限错误被 exists 吞成 False→返回 0)且 `_count_glob` 用会吞 scandir 错误的 `Path.glob()`,故不可读的 logpos/目录仍可能报 0。本轮:三 helper 只把 `FileNotFoundError` 解释为"不存在→0",`PermissionError`/其他 OSError 一律传播(→`_guard` 置 null);计数改 `os.scandir`(缺失→FileNotFoundError→0,不可读→PermissionError 传播)+ `fnmatch` 匹配。新增 A 档用例**直接执行 `_count_dirs`/`_count_glob` 的缺失与 scandir 访问失败路径**(monkeypatch `os.scandir` 抛 PermissionError,断言传播而非 0)。 |
| R-02 | major | `_last_cache_bytes` 原在淘汰前写入 `total`,淘汰递减局部 `total` 后未回写,`_collect_disk_sample` 因而发布淘汰前(可能 warn/critical)的用量一个 janitor 周期。修复:淘汰循环结束后 `self._last_cache_bytes = total`。新增回归用例:两个 100B 条目 + cap 150 → 淘汰一个 → 样本 cache.bytes == 100(而非 200),且被淘汰 sha 目录确已 rmtree。 |

## 测试结果

全量 `627 passed, 1 skipped`(TC-17 无 env 跳过,真 PG 由 tc17 脚本 pass)。
既有缓存淘汰用例(TC-11 等)全绿,`_last_cache_bytes` 回写未破坏淘汰逻辑。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-09 | A | pass | tc09-10-agent-disk.txt(7 采样用例:已知树 + `_volume` 抛错 null + `_dir_bytes` 缺失/不可读 + **count helper 缺失/scandir 权限失败** + scrapyd 不可读遍历→null + **缓存淘汰后样本=剩余大小**) |
| TC-10 | A | pass | tc09-10-agent-disk.txt(3 心跳用例含零遍历断言) |
| TC-15 | A | pass | tc15-pytest.txt(`627 passed`)、tc15-ruff.txt(clean);web 侧沿用 round-04 tc15-web-test.txt(`88 passed`,web 源码未变) |
| TC-17 | A | pass | tc17-postgres.txt(源码/脚本未变) |
| TC-01..08,11..14,16 | A/B | pass | 沿用前轮证据(相应源码未变) |

## 与方案的偏差

- 无新增偏差。采样 helper(如实反映访问失败)与缓存淘汰 `_tree_size`(容错不
  停摆)刻意分家的原则不变。
