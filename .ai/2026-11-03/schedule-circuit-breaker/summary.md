---
task: schedule-circuit-breaker
date: 2026-11-03
rounds: 3
verdict: pass
---

# 任务小结:调度熔断代替永久停用(半开试跑、熔断态与 enabled 分离、按失败分类分策略、通知分级)

需求原文:「你需要 stash 下来自爬虫的、对这个项目的优化意见……列举下你准备实施的优化项目」→「按推荐,开始 rawf-plan」
(另确认「dispatch 失败判 transient 同意」)。交付:连续出错不再置 `enabled=false`,改为独立存储的熔断态——瞬态失败
退避后自动半开试跑、成功自愈,真坏进入需人工态(模板换新制品时试跑一次);agent 透传爬虫 `outcome/class`;通知分级;
Web 显示熔断态并可复位。

## 改动

| 文件 | 摘要 |
|---|---|
| `packages/protocol/dopilot_protocol/streams.py` | `AgentEvent.outcome_class` 可选字段 |
| `apps/agent/dopilot_agent/scrapyd/stats.py`、`state/store.py`、`redis/commands.py`、`redis/events.py` | 最后一个 stats 块内解析 `'outcome/class'`(截断 64),随状态文件持久化与终态 / 重发事件透传 |
| `apps/server/migrations/versions/0016_schedule_circuit_breaker.py`(新)、`models/scheduling.py`、`models/execution.py`、`models/notification.py` | 7 个熔断列、账本与执行的 `outcome_class`、3 个通知类型 |
| `apps/server/dopilot_server/services/states.py` | 执行 / 任务结果分类 |
| `apps/server/dopilot_server/services/outcomes.py` | 熔断状态机(仅当前代际驱动)、SAVEPOINT 通知、24 小时升级 |
| `apps/server/dopilot_server/services/schedules.py` | 定时闸熔断判定与半开、held 拉取式换制品放行、复位、`update_schedule` 锁内重读、视图字段 |
| `apps/server/dopilot_server/services/events.py` | 落 `executions.outcome_class` |
| `apps/server/dopilot_server/api/v1/schedules.py`、`schemas.py` | `POST /schedules/{id}/breaker/reset`;`ScheduleView` 熔断字段 |
| `apps/server/dopilot_server/config/settings.py`、`loader.py` | 3 个退避 / 升级参数、环境变量与校验 |
| `apps/server/dopilot_server/redis/reconcile.py`、`app.py` | 删除停用后 reload 调度器的回调 |
| `apps/web/…`(types、schedules API、调度页、铃铛、zh / en 文案) | 熔断徽标、复位菜单、三个通知类型 |
| `configs/server.example.toml`、`server.docker.toml` | 新参数与语义注释 |
| `docs/decisions/0025-…md`(新)、`README.md`、`0021-…md`;`docs/architecture/02/03/04/06`、`README.md` | 决策与架构回写 |
| 测试:server 新增 3 个文件(SQLite 52 条、PG 8 条、迁移 1 条),改写 `test_outcomes.py` / `test_reconcile_outcomes.py`,`test_config.py` 新增 7 条;agent / protocol / web 相应新增 | 20 条 plan 用例全部 A 档留证 |

## 评审历程

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan 01 | fail | 半开超时递增代际会丢弃迟到结果;日志上限为 0 的判据;试跑期间再换制品;重启用锁内重读;通知失败中止 PG 事务;建单 / 下发边界 |
| plan 02 | fail | 制品比对与模板更新的竞态;复位 / 启用两种锁顺序的预期;模板批量更新与记录器的多行锁环 |
| plan 03 | pass | 1 条文字残留 minor(已修) |
| 实现 01 | fail | 旧代际结果可从 closed 再次跳闸(R-01);双调度并发用例未确证持锁顺序(R-02);缺 half_open tooltip 断言(R-03);升级文案写死 24 小时(R-04 minor) |
| 实现 02 | pass | 遗留 1 条 minor(即 R-04) |
| 实现 03 | pass | 按用户决定修该 minor;无问题(首次运行遇 codex「模型容量不足」异常,未产出结论,重跑后完成) |

## 范围核对

- 追加类偏差:无。
- 收窄 D-01:跳闸只对 `enabled=true` 的调度生效(沿用 0021 既有守卫;停用调度重新启用时熔断本就清零)——用户 2026-11-03 认可。
- 评审「范围核对」:plan 阶段指出的「closed 态复位额外清零」已撤回改为无操作;「半开期限到点也升级」已撤回;
  「dispatch 失败判 transient」已获用户确认。两轮实现评审范围核对均为「无」。
- 停车场(用户 2026-11-03「其余按推荐」):① 其余 7 处通知写入点未包 SAVEPOINT——记入后续任务;
  ② `test_artifacts` 一次偶发失败——放弃(之后多次全量未复现);③ `test_resource_stats` 的 PG 用例读取不同的环境变量名
  而被跳过——记入后续任务;④ 前端 `NotificationType` 缺 `attempt_no_progress`——记入后续任务;⑤ 私有脱敏规则未覆盖
  裸 appid 写法与一个下游项目名——记入后续任务(用户本机规则);⑥ 两条现已停用调度是否重新启用——记入后续(运维)。
- 计划外的后续任务(非本任务):任务二(D 按时间阈值、F 暴露执行结果)。

## 遗留 minor 及处置

- 实现 02 / R-01(即实现 01 / R-04):升级通知正文写死「24 小时」,而升级时长可配置 —— 用户决定:本次修(第 03 轮已修,评审 pass)
