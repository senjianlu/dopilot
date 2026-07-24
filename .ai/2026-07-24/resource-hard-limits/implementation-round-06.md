---
task: resource-hard-limits
round: 06
date: 2026-07-24
---

# 实现记录:第 06 轮(修复轮)

修复 review-round-05-fail 的唯一 blocker(R-01:TC-14 证据未逐个 service 断言
日志上限)。仅改 TC-14 校验脚本与其证据,无源码改动。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| .ai/2026-07-24/resource-hard-limits/evidence/tc14-compose-check.sh | **R-01(TC-14)**:改用 `docker compose config --format json` + python3 逐个 service 断言 `logging.options == {max-size:10m, max-file:3}`,任一 service 缺失即该文件 fail;redis 的 maxmemory/noeviction/auto-aof-rewrite 亦从渲染后的 command 逐项断言。取代原"整份结果至少出现一次 max-size"的弱检查 |
| evidence/tc14-compose-check.txt | 重新运行,含命令 + 完整输出(逐 service 一行)+ 退出码 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | TC-14 脚本改为逐个 service 断言:三份 compose 分别渲染 JSON,断言每个 service(all-in-one 7 个 / server-only 4 个 / agent-only 1 个)的 `logging.options` 恰为 `max-size=10m`、`max-file=3`;缺一即 fail。证据 `tc14-compose-check.txt` 逐行列出每个 service 的 logging.options 与判定,`all N services bounded: True`,`FAIL=0`,`# Exit code: 0`。 |

## 测试结果

仅 TC-14 证据更新;其余用例与源码不变(全量 `570 passed`、`ruff` clean 沿用
round-05 证据,未改动源码)。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-14 | A | pass | tc14-compose-check.txt（逐 service 断言 7+4+1 全绑定 + redis 三项 + `FAIL=0` + `# Exit code: 0`) |
| TC-01..13, TC-15..18 | A/B | pass | 沿用 round-05 证据(源码未变):tc15-pytest.txt（`570 passed`)、tc15-ruff.txt（clean）、tc01-18-resource-limits-verbose.txt、tc16-doc-config-refs.txt |

## 与方案的偏差

- 无源码改动;仅强化 TC-14 的 A 档校验脚本使其满足"每个 service"的证据契约。
- 偶发 flake(`test_wheel_started_orphan_recovered_as_lost`,与本任务无关)说明
  同前;tc15-pytest.txt 为干净全绿运行。
- 其余无偏差。
