---
task: schedule-circuit-breaker
round: 02
date: 2026-11-03
---

# 实现记录:第 02 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/server/dopilot_server/services/outcomes.py` | `_drive_breaker` 把「非当前代际直接返回」移到所有状态分支之前(含 `closed` 跳闸分支),旧代际结果在任何状态下都只入账 |
| `apps/server/tests/test_schedule_breaker.py` | 新增 `test_trip_never_fires_on_old_generation_outcome`:经真实记录器复现「当前代际跳闸 → 更早完成的当前代际成功迟到并关闭 → 旧代际失败入账」,断言不再跳闸、`breaker_artifact_id` 仍为空 |
| `apps/server/tests/test_schedule_breaker_pg.py` | 双调度并发用例改为确定性顺序:记录器事务持锁未提交时,先用另一会话 `FOR UPDATE NOWAIT` 证明两条调度行均被锁住,再在记录器提交之前完成模板更新并核对已提交,最后提交记录器 |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 熔断徽标用例补 `half_open` 的 `data-state` 与悬停 tooltip 文案断言 |

## plan 评审 minor 交接

仅第 1 轮填写(见 implementation-round-01.md)。

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | 代际守卫前移到 `_drive_breaker` 开头;新增回归用例(纳入 TC-06 的 `-k trip`)。反向验证:把守卫放回原位置时该用例失败,修复后通过(源码已恢复为修复版) |
| R-02 | major | 用例改为:记录器持锁(`NOWAIT` 探测确证)→ 模板更新在 `wait_for` 时限内提交 → 核对模板已更新 → 记录器提交;不再依赖 `gather` 的偶然时序。见 evidence/TC-13-r02.log |
| R-03 | major | 补 `half_open` 徽标悬停后出现 "a probe run is in flight" 的断言。见 evidence/TC-16-r02.log |

R-04(minor,升级通知正文写死「24 小时」)按「修复轮只修 blocker / major」未处理,收尾时作为遗留 minor 交用户。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/TC-01.log(本轮未改 agent,沿用第 01 轮) |
| TC-02 | A | pass | evidence/TC-02.log(同上) |
| TC-03 | A | pass | evidence/TC-03.log(本轮未改协议,沿用第 01 轮) |
| TC-04 | A | pass | evidence/TC-04-r02.log(5 passed) |
| TC-05 | A | pass | evidence/TC-05-r02.log(3 passed) |
| TC-06 | A | pass | evidence/TC-06-r02.log(7 passed,含新增旧代际回归用例) |
| TC-07 | A | pass | evidence/TC-07-r02.log(8 passed) |
| TC-08 | A | pass | evidence/TC-08-r02.log(15 passed) |
| TC-09 | A | pass | evidence/TC-09-r02.log(4 passed) |
| TC-10 | A | pass | evidence/TC-10-r02.log(14 passed) |
| TC-11 | A | pass | evidence/TC-11-r02.log(7 passed) |
| TC-12 | A | pass | evidence/TC-12-r02.log(1 passed,PG 实跑) |
| TC-13 | A | pass | evidence/TC-13-r02.log(8 passed,PG 实跑) |
| TC-14 | A | pass | evidence/TC-14-r02.log(622 passed、1 skipped、0 fail;skip 同第 01 轮,为既有 `test_resource_stats.py`) |
| TC-15 | A | pass | evidence/TC-15-r02.log(agent + protocol 通过;ruff All checks passed) |
| TC-16 | A | pass | evidence/TC-16-r02.log(37 passed) |
| TC-17 | A | pass | evidence/TC-17-r02.log(134 passed;tsc、eslint、next build 成功) |
| TC-18 | A | pass | evidence/TC-18.log(本轮未改文档 / 配置 / 文案,沿用第 01 轮) |
| TC-19 | A | pass | evidence/TC-19-r02.log(95 个新增 / 修改文件,0 命中) |
| TC-20 | A | pass | evidence/TC-20-r02.log(2 passed) |

## 与方案的偏差

| 编号 | 类型 | 内容 | 原因 | 处置 |
|---|---|---|---|---|
| D-01 | 收窄 | 同第 01 轮:跳闸只对 `enabled=true` 的调度生效 | 见 implementation-round-01.md D-01 | 第 01 轮评审未就此提出问题,仍待用户确认 |

## 停车场

同第 01 轮(见 implementation-round-01.md「停车场」),本轮无新增。
