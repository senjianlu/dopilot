---
task: maintenance-resource-dashboard
round: 02
date: 2026-07-24
---

# 实现记录:第 02 轮(修复轮)

修复 review-round-01-fail 的 2 blocker + 2 major。全部为**测试覆盖/证据补全**,
无源码逻辑改动(端点/loop/采样行为在第 01 轮已正确)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/server/tests/test_resource_stats.py | 新增 `test_tc05_sweep_now_prune_fails_others_run`(R-03);新增 `test_tc07_lifespan_gates_stats_loop`(R-04,真跑 lifespan);新增 `test_tc08_stats_interval_toml` 且 env 测试改为 TOML 已设值时 env 仍胜出(R-01) |
| evidence/tc09-10-agent-disk.txt | 重生成:改用显式 4 个节点 id(2×TC-09 + 2×TC-10),`-k tc09` 曾把 TC-10 误 deselect(R-01) |
| evidence/tc01-11-server-resource-stats.txt | 重生成(含新增三用例) |
| evidence/tc17-postgres.txt | 重生成:外层加 `# CMD: bash …/tc17-postgres.sh` 与 `# Script exit code: 0`(R-02) |
| evidence/tc15-pytest.txt、tc15-ruff.txt | 重生成(`616 passed`) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | (a) **TC-10 证据缺失**:原命令 `-k tc09` 会对同批收集的 heartbeat 测试生效,把两个 disk 心跳用例 deselect → TC-10 实际未跑。改用显式测试 id 分别列 TC-09×2 + TC-10×2,`tc09-10-agent-disk.txt` 现 `4 passed` 含两个 `test_build_request_*disk*`。(b) **TC-08 TOML 覆盖**:新增 `test_tc08_stats_interval_toml`(TOML 设 17、无 env → 生效 17);env 用例改为 TOML=17 且 env=5 → env 胜出,兼证两通道。(c) TC-05/TC-07 缺口见 R-03/R-04。 |
| R-02 | blocker | `tc17-postgres.txt` 外层补 `# CMD: bash …/tc17-postgres.sh` 与脚本最终 `# Script exit code: 0`,满足"命令 + 完整输出 + 退出码";脚本文件保留。 |
| R-03 | major | 新增 `test_tc05_sweep_now_prune_fails_others_run`:patch `maintenance.prune_event_audit` 抛错,断言 `cleanup=ok`、`event_audit=failed`、`stream_trim=ok`(prune 失败后 trim 仍执行)、HTTP 200。 |
| R-04 | major | 新增 `test_tc07_lifespan_gates_stats_loop`:patch app 模块的重依赖(build_redis/dispatcher/consumers/reconcile/retention/schedule/seed),经 `app.router.lifespan_context` 真跑 lifespan——`stats_interval_seconds=0` 时 ResourceStatsLoop **未构造**且 `app.state.resource_stats is None`;`=60` 时构造一次。端点空响应 + 零采样由既有 `test_tc04_no_snapshot_zero_sampling` 覆盖(计数 stub 断言 `calls==0`)。 |

## 测试结果

档位照抄 plan。全量 `616 passed, 1 skipped`(跳过项 TC-17 在无
`DOPILOT_TEST_PG_URL` 时;真 PG 由 tc17 脚本补跑 pass)。仅列本轮受影响用例,
其余沿用 round-01 证据(源码未变)。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-05 | A | pass | tc01-11-server-resource-stats.txt(新增 `test_tc05_sweep_now_prune_fails_others_run` + 既有 cleanup 失败/单流失败/无 redis/retention 0) |
| TC-07 | A | pass | tc01-11-server-resource-stats.txt(新增 `test_tc07_lifespan_gates_stats_loop` + 既有 loop 恢复 + retention 0) |
| TC-08 | A | pass | tc01-11-server-resource-stats.txt(新增 TOML 用例 + env 胜出用例 + 默认 60) |
| TC-10 | A | pass | tc09-10-agent-disk.txt(`4 passed`,含 `test_build_request_includes_disk_sample`/`_omits_disk_when_no_sample`) |
| TC-17 | A | pass | tc17-postgres.txt(外层命令 + 完整输出 + `# Script exit code: 0`) |
| TC-15 | A | pass | tc15-pytest.txt(`616 passed`)、tc15-ruff.txt(clean);web 侧沿用 round-01 tc15-web-*.txt(源码未动) |
| TC-01..04,06,09,11..14,16 | A/B | pass | 沿用 round-01 证据(相应源码/文档未变) |

## 与方案的偏差

- 无新增偏差(round-01 的两处放置类偏差仍适用:`DiskStatus` 独立模块避免循环
  import、Progress 中性填充)。本轮纯补测试与证据。
