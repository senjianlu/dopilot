---
task: disable-all-schedules
date: 2026-08-10
rounds: 1
verdict: pass
---

# 任务小结:调度页「一键停用全部」按钮(升级前操作)

## 改动

| 文件 | 摘要 |
|---|---|
| apps/server/dopilot_server/services/schedules.py | `disable_all_schedules`(单事务批量 UPDATE)+ `count_enabled_schedules`(全局 COUNT) |
| apps/server/dopilot_server/api/v1/schemas.py | `SchedulesResponse.enabled_total`;`ScheduleDisableAllResponse` |
| apps/server/dopilot_server/api/v1/schedules.py | `POST /schedules/disable-all`(admin 鉴权,恰好一次 runner reload,幂等);列表填充 `enabled_total` |
| apps/web/lib/api/types.ts、schedules.ts | 类型与 API 客户端(`listSchedules` 返回完整响应、`disableAllSchedules`) |
| apps/web/app/(app)/schedules/page.tsx | 「一键停用」按钮:可用性/文案数量取 `enabled_total`,destructive 确认框,在途禁用防重复 |
| apps/web/lib/i18n/locales/zh.ts、en.ts | `disableAll` / `confirmDisableAll` 文案 |
| apps/server/tests/test_schedules.py、apps/web .../schedules.test.tsx | 10 条用例全 A 档落地 |

docs 回写:不需要——Schedule 领域语义未变(02-domain-model 无需更新),
纯增量运维端点 + 列表元数据。

## 评审历程

plan 阶段(用户要求执行并授权上限 10 轮,实际 3 轮):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 1 | fail | 2 major:runner reload 恰一次无验证;在途禁用/防重复无用例 → 补 TC-07/TC-08 |
| 2 | fail | 1 major:按钮可用性依赖 200 条截断列表 → 服务端 `enabled_total` + TC-09/TC-10 |
| 3 | pass | — |

实现阶段(上限 10 轮,实际 1 轮):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 1 | pass | — |

## 遗留 minor 及处置

无(评审问题清单为空)。
