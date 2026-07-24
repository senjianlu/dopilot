---
task: maintenance-resource-dashboard
round: 07
date: 2026-07-24
---

# 实现记录:第 07 轮(修复轮 + 访问失败语义一次性审计)

修复 review-round-06-fail 的 1 blocker(R-01)+ 1 major(R-02),并按用户
要求对**所有** size/count helper(agent + server)做一次访问失败语义完整审计,
把同类残留一次扫净。修复轮上限经用户第三次授权由 6 放宽至 10
(plan.md `impl_fix_max_rounds: 10`)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| .ai/.../plan.md | frontmatter `impl_fix_max_rounds: 10` + 三次授权注释 |
| apps/agent/dopilot_agent/janitor.py | **R-01**:`_count_dirs` 的 `entry.is_dir()` 只跳过 `FileNotFoundError`(条目消失),`PermissionError` 传播(原 `except OSError` 会吞成偏小计数)。**审计**:磁盘样本的 cache 字节改为**直接** `_dir_bytes(artifacts_root)` 测量(严格语义),不再复用 eviction 的容错 `_tree_size` 结果——顺带移除 `_last_cache_bytes` 字段与两处回写(样本天然反映淘汰后真实树,取代 round-06 的回写方案) |
| apps/server/dopilot_server/resource_stats.py | **R-02**:`_du` 去掉 `os.path.exists()` 门控(它会把 `PermissionError` 吞成 False→返回 0),改为 `os.walk(onerror=_raise)` + 只把 `FileNotFoundError` 当"不存在→0",`PermissionError`/其他 OSError → `None`(unknown);文件中途消失(stat FileNotFoundError)benign 跳过 |
| apps/agent/tests/test_resource_limits.py | 新增 `test_tc09_count_dirs_entry_access_failure_propagates`(is_dir() PermissionError 传播、FileNotFoundError 跳过);既有 cache 淘汰样本用例改经 `_dir_bytes` 仍绿 |
| apps/server/tests/test_resource_stats.py | `test_tc03_du_access_failure_is_unknown` 改用 PermissionError(去 exists 门控后仍→None);新增 `test_tc03_du_vanished_file_mid_walk_is_benign`(stat FileNotFoundError→跳过、不误判访问失败) |
| evidence/tc09-10-agent-disk.txt、tc01-11-server-resource-stats.txt、tc15-pytest.txt、tc15-ruff.txt、tc17-postgres.txt | 重生成;tc09-10 首行改为**真实可执行命令**(R-01 指出的伪命令已修) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | (a)`_count_dirs` 的 `except OSError` 会吞掉 `entry.is_dir()` 的 PermissionError→偏小"正常"计数。改为只跳过 `FileNotFoundError`,PermissionError 传播→`_guard` 置 null。新增 A 档用例直接覆盖 `entry.is_dir()` 抛 PermissionError(传播)与 FileNotFoundError(跳过、其余照常计数)。(b)tc09-10 证据首行原为说明性文字 `… -k tc09 -v AND …`,已改为单条真实命令 `python -m pytest <两文件> -k "tc09 or disk_sample or reads_cache or omits_disk or includes_disk" -v`,`11 passed` + 退出码 0。 |
| R-02 | major | server `_du` 原 `if not os.path.exists(path): return 0`——`os.path.exists` 在权限错误下返回 False,把访问故障伪装成"不存在→0"。改为 `os.walk(onerror=_raise)`:只有 `FileNotFoundError`(顶层目录不存在)→0,`PermissionError`/其他 OSError→`None`(unknown 条目,scope 仍 ok)。新增/更正回归用例:PermissionError→None、中途消失文件→benign 跳过。 |
| 审计(用户要求) | — | 对全部 size/count helper 核查零值误报:server `_du`(已修)、`_distinct_volumes`/`_disk_usage`(失败→跳过该卷条目,非零值误报,可接受);agent `_dir_bytes`(os.walk onerror=_raise,PermissionError 传播)、`_count_dirs`(已修)、`_count_glob`(os.scandir + fnmatch,FileNotFoundError→0 其余传播)、`_volume`(disk_usage 抛错→null)。**唯一残留**:样本 cache 字节曾复用 eviction 的容错 `_tree_size`(不可读 sha 目录会低报)——本轮改为样本内 `_dir_bytes(artifacts_root)` 严格测量,彻底消除该类。 |

## 测试结果

全量 `629 passed, 1 skipped`(TC-17 无 env 跳过,真 PG 由 tc17 脚本 pass);
既有缓存淘汰用例全绿(移除 `_last_cache_bytes` 未破坏淘汰逻辑)。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-09 | A | pass | tc09-10-agent-disk.txt(8 采样用例:含 `_count_dirs` entry 访问失败传播、count helper scandir 失败、`_dir_bytes` 缺失/不可读、scrapyd 遍历 null、缓存淘汰后严格测量=剩余) |
| TC-10 | A | pass | tc09-10-agent-disk.txt(3 心跳用例含零遍历断言;真实命令 `11 passed`) |
| TC-01/03 | A | pass | tc01-11-server-resource-stats.txt(`_du` PermissionError→None、中途消失文件→0、缺失→0;nodes 读失败→agents unavailable) |
| TC-15 | A | pass | tc15-pytest.txt(`629 passed`)、tc15-ruff.txt(clean);web 沿用 round-04 tc15-web-test.txt(`88 passed`,web 源码未变) |
| TC-17 | A | pass | tc17-postgres.txt(重跑真 PG,`# Script exit code: 0`) |
| TC-02,04..08,11..14,16 | A/B | pass | 沿用前轮证据(相应源码未变) |

## 与方案的偏差

- **样本 cache 字节不再复用 eviction total**:plan 曾写"复用 `_sweep_cache` 已算
  出的 total 避免二次遍历"。为让 cache 指标获得与其他子项一致的访问失败严格
  语义(不可读 sha 目录→null 而非低报),改为样本内 `_dir_bytes(artifacts_root)`
  直接测量;每 600s 多一次 artifacts 树遍历,开销可忽略。功能面/配置面不变,
  可观测正确性更强。
- 其余无新增偏差(`DiskStatus` 独立模块、Progress 中性填充仍适用)。
