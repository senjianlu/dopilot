---
task: schedule-circuit-breaker
round: 01
date: 2026-11-03
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `packages/protocol/dopilot_protocol/streams.py` | `AgentEvent.outcome_class: str \| None = None`(可选,旧 agent / 旧 server 互不影响) |
| `apps/agent/dopilot_agent/scrapyd/stats.py` | `ScrapyStats.outcome_class`:只在最后一个 stats 块内按 `'outcome/class':\s*'([^']+)'` 取值,UTF-8 容错解码,截断 64 字符 |
| `apps/agent/dopilot_agent/state/store.py` | `AttemptState.outcome_class`(默认 None,旧状态文件照常加载);`mark_stats` 增参 |
| `apps/agent/dopilot_agent/redis/commands.py`、`redis/events.py` | scrapy 终态事件与按状态文件重发的终态事件带 `outcome_class` |
| `apps/server/dopilot_server/models/scheduling.py` | `Schedule` 新增 7 个熔断列;`ScheduleOutcomeLedger.outcome_class` |
| `apps/server/dopilot_server/models/execution.py` | `Execution.outcome_class`(String(64)) |
| `apps/server/dopilot_server/models/notification.py` | `schedule_breaker_open/held/closed` 三个类型常量;旧 `schedule_auto_disabled` 标注为历史 |
| `apps/server/migrations/versions/0016_schedule_circuit_breaker.py`(新) | 上述列;`breaker_state` / `breaker_level` 非空带 server default,其余可空;downgrade 全部删除 |
| `apps/server/dopilot_server/config/settings.py`、`config/loader.py` | 三个退避 / 升级参数、对应环境变量;覆盖之后校验(base ≥ 1、max ≥ base、escalate ≥ 0),不合法即 `ConfigError` |
| `apps/server/dopilot_server/services/states.py` | `execution_outcome_class` / `task_outcome_class`:server 自身判据(条件与 `execution_is_erroneous` 逐字一致)→ broken;`lost` / `dispatch_unavailable` / `dispatch_timeout` → transient;爬虫 `transient` → transient;其余 broken;任务级 ok / neutral |
| `apps/server/dopilot_server/services/events.py` | 终态事件的 `outcome_class` 落 `executions.outcome_class`(server 侧再截断 64) |
| `apps/server/dopilot_server/services/outcomes.py` | 记录器为调度任务分类并写账本 `outcome_class`;`_drive_breaker` 按 plan 状态表驱动熔断(跳闸 open/held、半开结果、open/held 遇 ok 关闭、旧代际只入账);`notify_safely` 用 SAVEPOINT 包住通知;24 小时升级;返回跳闸调度 id |
| `apps/server/dopilot_server/services/schedules.py` | `acquire_firing_slot` 末尾(含 `max_concurrency=0` 的提前放行分支)接熔断闸 `_admit_breaker`:open 退避 / 到点转 half_open(代际 + 1)/ half_open 期限到点同代际再放行 / held 拉取式比较模板当前制品;`reset_schedule_breaker`;`update_schedule` 先 `FOR UPDATE` 锁内重读,`enabled` 假→真时一并清熔断;视图字段;`SKIP_BREAKER` |
| `apps/server/dopilot_server/api/v1/schedules.py`、`api/v1/schemas.py` | `POST /schedules/{id}/breaker/reset`;`ScheduleView` 熔断字段 |
| `apps/server/dopilot_server/redis/reconcile.py`、`app.py` | 删除「自动禁用后 reload 调度器」回调 |
| `apps/web/lib/api/types.ts`、`lib/api/schedules.ts` | `BreakerState` 与熔断字段;三个通知类型;`resetScheduleBreaker` |
| `apps/web/app/(app)/schedules/page.tsx` | 名称旁熔断徽标(open / half_open / held,tooltip)与旧徽标并列;非 closed 时行菜单「复位熔断」 |
| `apps/web/components/layout/notification-bell.tsx` | 三个新类型跳 `/schedules?highlight=<id>`;`payload.escalated` 时取 `body_escalated` |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | 徽标、复位、三个通知类型(含 `body_escalated`)文案 |
| `configs/server.example.toml`、`configs/server.docker.toml` | 熔断语义注释与三个新参数 |
| `docs/decisions/0025-schedule-circuit-breaker.md`(新)、`docs/decisions/README.md`、`docs/decisions/0021-…md` | 新决策、索引行、0021 顶部「§6 停用动作由 0025 取代」 |
| `docs/architecture/02-domain-model.md`、`03-execution-and-logs.md`、`04-configuration.md`、`06-web-frontend.md`、`README.md` | 字段、分类与状态机、配置、界面;03 章节改名并同步 06 锚点 |
| 测试:`apps/server/tests/test_schedule_breaker.py`(新)、`test_schedule_breaker_pg.py`(新)、`test_migration_0016_pg.py`(新);改写 `test_outcomes.py`(5 个断言 `enabled=false` 的用例改为熔断语义)、`test_reconcile_outcomes.py`(reload 回调用例改为「不 reload」);`test_config.py` 新增 breaker 用例;agent `test_scrapyd_stats.py` / `test_log_flood.py` / `test_event_outbox.py`;protocol `test_stream_schemas.py`;web `schedules.test.tsx`、`notification-bell.test.tsx` | 见测试结果 |
| `.ai/2026-11-03/schedule-circuit-breaker/assets/*-redacted.md`、`evidence/docs-config-check.sh` | 爬虫建议原件经 `redact.py` 脱敏的副本(另手工遮掉 1 处裸 appid、1 处下游项目名,脱敏检查 0 命中);TC-18 断言脚本 |

## plan 评审 minor 交接

| 来源 | 内容 | 处置 |
|---|---|---|
| 01/R-07 | TC-12 将所有新列写为可空，与已明确的非空列定义不一致。 | 已在 plan 修订中解决(第 1 轮后改为分别断言) |
| 01/R-08 | TC-18 的断言脚本路径与留证命令的工作目录不匹配。 | 已在 plan 修订中解决(改为任务目录下脚本的仓库相对路径) |
| 01/R-09 | 风险说明把退避上限表述成了实际试跑间隔上限。 | 已在 plan 修订中解决 |
| 03/R-01 | 通知章节仍残留定时闸触发升级的旧表述。 | 已在 plan 修订中解决(第 3 轮 pass 后删除该句) |

## 修复对照

不适用(第 1 轮)。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/TC-01.log(14 passed,含 6 条 `outcome/class` 用例) |
| TC-02 | A | pass | evidence/TC-02.log(9 passed:终态事件、状态文件重发、旧状态文件 + stats 解析) |
| TC-03 | A | pass | evidence/TC-03.log(21 passed) |
| TC-04 | A | pass | evidence/TC-04.log(5 passed) |
| TC-05 | A | pass | evidence/TC-05.log(3 passed) |
| TC-06 | A | pass | evidence/TC-06.log(6 passed) |
| TC-07 | A | pass | evidence/TC-07.log(8 passed) |
| TC-08 | A | pass | evidence/TC-08.log(15 passed,含迟到 lost 与超时后成功的长任务) |
| TC-09 | A | pass | evidence/TC-09.log(4 passed) |
| TC-10 | A | pass | evidence/TC-10.log(14 passed;`-k` 关键字另选中 2 条名称含 enabled / resets 的跳闸用例,同样通过) |
| TC-11 | A | pass | evidence/TC-11.log(7 passed) |
| TC-12 | A | pass | evidence/TC-12.log(1 passed,PG 实跑) |
| TC-13 | A | pass | evidence/TC-13.log(8 passed,PG 实跑) |
| TC-14 | A | pass | evidence/TC-14.log(621 passed、1 skipped、0 fail;skip 为既有的 `test_resource_stats.py`,它读取另一个环境变量 `DOPILOT_TEST_PG_URL`,与本任务无关) |
| TC-15 | A | pass | evidence/TC-15.log(agent + protocol 306 passed;ruff All checks passed) |
| TC-16 | A | pass | evidence/TC-16.log(2 文件 37 passed) |
| TC-17 | A | pass | evidence/TC-17.log(16 文件 134 passed;tsc、eslint、next build 成功) |
| TC-18 | A | pass | evidence/TC-18.log(29 条断言全部 PASS) |
| TC-19 | A | pass | evidence/TC-19.log(77 个新增 / 修改文件,0 命中) |
| TC-20 | A | pass | evidence/TC-20.log(2 passed) |

补充核验(不替代上表):TC-13 的通知故障注入用例做过反向验证——临时去掉 `notify_safely` 的 SAVEPOINT 后该用例失败,恢复后通过(源码已恢复,未留痕)。本机 dev 库容器 `docker-db-1` 原为停止状态,本轮为跑 PG 用例将其启动。

## 与方案的偏差

| 编号 | 类型 | 内容 | 原因 | 处置 |
|---|---|---|---|---|
| D-01 | 收窄 | 跳闸只对 `enabled=true` 的调度生效(plan 状态表未写此条件) | 沿用 0021 既有守卫:停用的调度只会被 trigger-now 触发、没有定时可拦,且重新启用时熔断本就会清零,对它跳闸只会产生无用通知;03 文档与决策 0025 已写明「仅已启用的调度」 | 如实记录,交评审 / 用户确认 |

## 停车场

- 其余 7 处通知写入点(`services/logs.py`、`services/events.py`、`services/maintenance.py` ×2、`redis/reconcile.py`、`redis/stream_guard.py`、`redis/dispatcher.py`)仍是「try/except 包通知、与业务写同一事务」,PG 上通知语句失败同样会使所在事务中止;本任务只修了熔断通知(`notify_safely`),是否统一改为 SAVEPOINT 待用户决定。
- `apps/server/tests/test_artifacts.py::test_reupload_identical_bytes_preserves_archive_state` 在本轮第一次全量运行中失败过一次,单跑及之后两次全量(含 TC-14)均通过,疑似既有的偶发不稳定,与本任务无关。
- `test_resource_stats.py` 的 PG 用例读取 `DOPILOT_TEST_PG_URL`,与其余 PG 用例的 `DOPILOT_TEST_DATABASE_URL` 不一致,导致全量回归时被跳过。
- 前端 `NotificationType` 联合类型缺少既有的 `attempt_no_progress`(不影响运行,渲染按字符串 type 走 i18n)。
- 私有脱敏规则未覆盖「`<站点> gN / <appid>`」写法中的裸 appid 与一个下游项目名(本任务脱敏副本已手工遮掉),规则是否补充待用户决定。
- 两条现已停用的调度是否重新启用(运维动作,plan 非目标)。
