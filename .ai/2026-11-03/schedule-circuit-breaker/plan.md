---
status: approved
task: schedule-circuit-breaker
date: 2026-11-03
approved_at: 2026-11-03 11:32 +0900(依据用户 2026-11-03「确认,开始 rawf-implement」;plan 评审第 03 轮 pass)
evidence_format: v1
---

# 方案:调度熔断代替永久停用(半开试跑、熔断态与 enabled 分离、按失败分类分策略、通知分级)

## 需求原文

> 你需要 stash 下来自爬虫的、对这个项目的优化意见。然后看下 spider 项目是否做好了接入优化后 dopilot 的准备。
> 然后列举下你准备实施的优化项目，等我确认后我们再开始 rawf 流程。

> 按推荐,开始 rawf-plan

「按推荐」所指(2026-11-03 本会话列出、用户整体确认的推荐项):

1. 拆两个任务:**本任务 = A + B + C + E**(熔断代替永久停用、熔断态与 `enabled` 分离、读爬虫 `outcome/class`
   按类分策略、通知分级,含 Web 显示与复位);D(按时间算阈值)与 F(API 暴露执行结果)另立任务二。
2. `broken` 达阈值进入「需人工」熔断态:不改 `enabled`、不自动试跑;**模板换新制品时放一次半开试跑**。
3. 默认参数:阈值 5 次;退避 15 分钟 → 30 分钟 → 1 小时 → 2 小时封顶;熔断持续 24 小时后,于下一次试跑失败时升级为 error。
4. 节点失联(`lost`)判 `transient`。
5. 迁移不动已被自动停用的旧调度(仍 `enabled=false`,由用户手动启用)。

plan 评审第 1 轮后补充的对齐结论(用户原话:「dispatch 失败判 transient 同意」):命令下发失败
(`dispatch_unavailable` / `dispatch_timeout`)与 `lost` 一样判 `transient`。

建议来源:crawler-a 会话 2026-11-02 的问题记录(原件未脱敏,只留在本机 git stash;脱敏副本见
`assets/upstream-issue-redacted.md`、`assets/incident-history-redacted.md`)。

**本任务交付**:连续出错不再把调度 `enabled` 置假,而是进入独立存储的熔断态——瞬态失败按指数退避自动半开试跑、
成功即自愈,真坏(`broken`)进入需人工态(换新制品时试跑一次);agent 透传爬虫 stats 的 `outcome/class`,
server 据此与自身判据分类;通知分「熔断 / 需人工 / 恢复 / 24 小时升级」;Web 调度页显示熔断态并可复位。

## 背景与目标

**现象**(脱敏副本 `assets/upstream-issue-redacted.md`):10-31 两条调度因瞬态失败(市场变薄 5 小时、出口 403 共 5 分钟)
连续 5 次出错被自动停用,上游数小时内即恢复,但调度停了 35~40 小时,只因没人手动重新启用。同期全站 24 小时 14,494 轮、
失败 56 轮(0.39%)、最长连续失败 2。历次停用复盘(`assets/incident-history-redacted.md`)显示大多数由瞬态引起,
真正需要人工的(上游改版、套餐到期、额度耗尽)反而和瞬态混在同一个「连续 5 次」里。

**dopilot 侧代码事实**(当前 HEAD `52727f0` 逐条亲核):

- 判错是一位信号:`apps/server/dopilot_server/services/states.py:240` `execution_is_erroneous`,不区分原因;
  agent 只解析 `log_count/ERROR` 与 `finish_reason` 两个键(`apps/agent/dopilot_agent/scrapyd/stats.py:21-22`)。
- 达阈值直接 `schedule.enabled = False`(`apps/server/dopilot_server/services/outcomes.py:246`),永久,
  只能手动重启用恢复(`apps/server/dopilot_server/services/schedules.py:222-233`)。
- 爬虫的声明式同步每次发版对每条调度 `PUT enabled=<toml 值>`(crawler-a `scripts/dopilot_sync.py` reconcile),
  所以停用写在 `enabled` 上会与 toml 打架:不发版一直停、一发版被拉起。
- 决策 0021 §6 设自动停用的初衷是拦住日志洪泛类坏爬虫(`docs/decisions/0021-log-flood-guard-and-auto-disable.md:45-50`),
  此初衷必须保留。

**爬虫侧接口现状**:crawler-a 提交 `bfd479c`(尚未推送)在每轮最后一个 `Dumping Scrapy stats` 块写
`'outcome/class': 'ok' | 'transient' | 'broken'`,与 `finish_reason` 同块;缺该键的项目 / 旧包语义不变。

**目标**:瞬态故障自愈不需要人;真坏的调度停住并以 error 通知人;`enabled` 只由人与声明式同步修改;
两侧任意顺序上线都安全。

## 改动范围

**协议与 agent**(C 的取数通道,实现必需)

| 文件 | 改动 |
|---|---|
| `packages/protocol/dopilot_protocol/streams.py` | `AgentEvent` 增可选 `outcome_class: str \| None = None` |
| `apps/agent/dopilot_agent/scrapyd/stats.py` | `ScrapyStats` 增 `outcome_class`,只在最后一个 stats 块内取 `'outcome/class'` |
| `apps/agent/dopilot_agent/state/store.py` | `AttemptState.outcome_class`(默认 None,旧状态文件照常加载);`mark_stats` 增参 |
| `apps/agent/dopilot_agent/redis/commands.py`、`redis/events.py` | 终态与按状态文件重发的终态事件带上 `outcome_class` |

**server**

| 文件 | 改动 |
|---|---|
| `models/scheduling.py` | `Schedule` 增熔断列;`ScheduleOutcomeLedger` 增 `outcome_class` |
| `models/execution.py` | `Execution.outcome_class` |
| `models/notification.py` | 三个新通知类型常量 |
| `migrations/versions/0016_schedule_circuit_breaker.py`(新) | 上述列 |
| `services/states.py` | 执行 / 任务结果分类函数 |
| `services/events.py` | 终态事件落 `outcome_class` |
| `services/outcomes.py` | 记录结果后驱动熔断状态机(替代 `enabled=false`) |
| `services/schedules.py` | 定时闸加熔断判定与半开(含「需人工」态在模板换制品后的放行);复位;`enabled` 假→真时一并复位(锁内);视图字段 |
| `api/v1/schedules.py`、`api/v1/schemas.py` | 复位端点;`ScheduleView` 熔断字段 |
| `config/settings.py`、`config/loader.py` | 三个退避 / 升级参数与环境变量 |
| `redis/reconcile.py`、`app.py` | 删除「自动禁用后 reload 调度器」回调——熔断不改 `enabled`,不需要 reload;保留它会在每次熔断时无谓重建全部 interval 任务、打乱其触发相位(实现必需) |

**Web**:`lib/api/types.ts`、`lib/api/schedules.ts`、`app/(app)/schedules/page.tsx`、
`components/layout/notification-bell.tsx`、`lib/i18n/locales/zh.ts`、`en.ts`。

**配置样例**:`configs/server.example.toml`、`configs/server.docker.toml`(新参数与注释)。

**文档**(决策变化须回写,AGENTS.md 硬规则):`docs/decisions/0025-schedule-circuit-breaker.md`(新)、
`docs/decisions/README.md`(索引行)、`docs/decisions/0021-…md`(顶部加一行「§6 的停用动作由 0025 取代」);
`docs/architecture/02-domain-model.md`、`03-execution-and-logs.md`、`04-configuration.md`、`06-web-frontend.md`、
`README.md`(导航行文字)。

**测试**:server `tests/test_schedule_breaker.py`(新)、`tests/test_schedule_breaker_pg.py`(新)、
`tests/test_migration_0016_pg.py`(新);改写 `tests/test_outcomes.py`、`tests/test_reconcile_outcomes.py`、
`tests/test_config.py` 中受影响的用例(断言 `enabled=false` / reload 回调的旧用例随行为变化改写);
agent `tests/test_scrapyd_stats.py` 与终态路径用例;protocol `tests/test_stream_schemas.py`;
web `schedules/__tests__/schedules.test.tsx`、`layout/__tests__/notification-bell.test.tsx`。

**明确不动**:连错判定口径本身(`execution_is_erroneous` 的条件)、账本自修剪与代际机制、
并发闸(决策 0022)、trigger-now 的放行规则、`disable-all`、模板服务(`services/templates.py`,换制品不联动调度行)、爬虫仓库任何文件。

## 非目标

- D 按时间算阈值、F API / 任务详情暴露 `finish_reason` / `error_count` / 分类——任务二。
- 每条调度单独配置阈值 / 退避(爬虫 toml 与同步脚本需随改)——停车场。
- 首次 `broken` 即通知(先观察分类上线后的分布)——停车场。
- python_wheel 用退出码(如 75)声明瞬态——停车场;本任务中 python_wheel 无 stats,按下述规则即与今天同口径。
- 数据新鲜度告警——另议。
- `no_target` / `canceled` 在连错计数里算「非出错」的既有口径不变(只在熔断状态机里另作「中性」处理,见下)。
- 把已被自动停用的旧调度迁入熔断态或自动启用(用户确认不动)。
- 重命名 `auto_disable_after_errors` 配置键(保留键名与环境变量以免破坏现有部署,只改语义说明)。
- 两条现已停用调度的重新启用(运维动作,由用户决定)。

## 实现方案

### 1. 结果分类(server 侧,`states.py`)

对**出错**的执行(`execution_is_erroneous` 为真)分类,优先级自上而下:

1. **server 自身判据一律 `broken`**,条件与 `execution_is_erroneous` 现有写法逐字一致(`states.py:258-275`):
   `error_code == log_flood`;日志文件 `truncated` 且原因属 `size-cap` / `dir-budget`;`max_file_bytes > 0` 且上报的
   `log_bytes` 非空且 `≥ max_file_bytes`(上限为 0 = 关闭时永不命中本条)——不采信爬虫自报,守住 0021 的初衷;
2. 平台侧故障 → `transient`:执行状态 `lost`(用户确认),或 `error_code` 为 `dispatch_unavailable` / `dispatch_timeout`
   (命令未能投递到 agent,`redis/dispatcher.py:55-56`;与 `lost` 同属平台而非爬虫的问题,否则一次 Redis 故障撞上试跑
   就会把调度打入需人工态);
3. 执行的 `outcome_class == "transient"` → `transient`;
4. 其余(含 `broken`、`ok`、缺失、未知值、无 stats 的 failed)→ `broken`。

任务级结果类 `ok | neutral | transient | broken`:

- 未出错:任务 `complete` → `ok`;其它(`canceled`、`no_target`)→ `neutral`;
- 出错:任一出错执行为 `broken` → `broken`;出错执行全为 `transient` → `transient`;
  无出错执行而因任务自身状态判错(防御分支)→ `lost` 判 `transient`,否则 `broken`。

账本行记录该类(`ScheduleOutcomeLedger.outcome_class`);迁移前的历史出错行该列为 NULL,一律按 `broken` 计。

### 2. 熔断状态机

`Schedule` 新列:`breaker_state`(`closed` | `open` | `half_open` | `held`,非空,默认 `closed`)、
`breaker_level`(非空整数,默认 0)、`breaker_opened_at`、`breaker_retry_at`、`breaker_escalated_at`(均可空时间)、
`breaker_reason`(可空 JSON:类型、连错数、阈值、末次出错任务等)、`breaker_artifact_id`(可空,进入 `held` 时触发任务所用的制品 id)。

退避 `backoff(level) = min(base × 2^level, max)`,默认 base 900 秒、max 7200 秒,即 15 分钟 / 30 分钟 / 1 小时 / 2 小时。
「当前代际结果」= 刚记录的账本行 `generation == schedule.outcome_generation`;旧代际结果只入账,不驱动状态(沿用 0021)。
**代际只在两类时机递增**:进入 `half_open`(自 `open` 或 `held`,把试跑之前创建的在途任务隔离到旧代际)与人为复位 / 重启用(重置边界)。
半开期限到点后的再试跑**不**递增代际,因此同一半开期内的各次试跑共享代际,谁的结果先记录谁决定转移,
迟到的 `lost`、超时仍成功的长任务都照常计入(后到者按届时状态处理)。

**「需人工」态的换制品放行(拉取式)**:进入 `held` 时把触发任务快照里的制品 id
(`tasks.template_snapshot.build_artifact.id`,`services/artifacts.py:267-271` 冻结)记入 `breaker_artifact_id`
(快照缺该字段的历史任务记 NULL)。定时闸在持有该调度行锁时读取所属模板**当前已提交**的 `build_artifact_id`,
与 `breaker_artifact_id` 不同即放行一次半开试跑。模板更新不触碰任何调度行,所以无论模板更新与「进入 `held`」
谁先提交,下一次定时触发都按提交后的两边取值判定——「试跑旧制品期间模板又换制品」时旧制品的 `broken`
封不住新制品,也不存在跨行批量加锁。

| 当前态 | 事件 | 新态与动作 |
|---|---|---|
| `closed` | 当前代际连错前缀 ≥ 阈值(阈值 > 0),且前缀**全为** `broken` | `held`;记 `opened_at`、`reason`;通知「需人工」(error) |
| `closed` | 同上,前缀含 `transient` | `open`;`level=0`、`retry_at=now+backoff(0)`、记 `opened_at` / `reason`;通知「熔断」(warning) |
| `open` | 定时触发,`now < retry_at` | 跳过(新跳过原因 `breaker`) |
| `open` | 定时触发,`now ≥ retry_at`,且存在 / 启用 / 积压 / 并发各闸均放行 | `half_open`;`outcome_generation + 1`、连错清零、`retry_at = now + max`(试跑期限);本次放行即试跑 |
| `half_open` | 定时触发,`now < retry_at` | 跳过(试跑在途) |
| `half_open` | 定时触发,`now ≥ retry_at`(试跑超过期限仍无结果),其余闸放行 | 仍 `half_open`;**代际不变**、`retry_at = now + max`;放行新试跑(试跑超时本身不算失败、不升退避级、不触发升级) |
| `held` | 定时触发,`breaker_artifact_id` 为 NULL 或等于模板当前制品 | 跳过 |
| `held` | 定时触发,`breaker_artifact_id` 非 NULL 且 ≠ 模板当前制品,其余闸放行 | `half_open`;`level=0`、代际 + 1、`retry_at = now + max`;本次放行即试跑新制品 |
| `half_open` | 当前代际结果 `ok` | `closed`;清熔断字段、`level=0`;通知「恢复」(info) |
| `half_open` | 当前代际结果 `transient` | `open`;`level=min(level+1, 封顶级)`、`retry_at=now+backoff(level)`;若升级阈值 > 0、尚未升级且 `now − opened_at ≥` 升级阈值 → 记 `escalated_at`,以 error 再发「熔断」通知 |
| `half_open` | 当前代际结果 `broken` | `held`;通知「需人工」(error) |
| `half_open` | 当前代际结果 `neutral`(试跑被取消 / 无可用节点) | `open`;`level` 不变、`retry_at = now`(下一次触发即重试) |
| `open` / `held` | 当前代际结果 `ok`(在途旧任务或手动 trigger-now 成功) | `closed`;通知「恢复」(info) |
| `open` / `held` | 当前代际结果出错或中性 | 状态不变(连错计数照常重算) |
| `open` / `half_open` / `held` | 手动复位 | `closed`;代际 + 1、连错清零、清熔断字段 |
| `closed` | 手动复位 | 无操作(不改代际与计数),返回当前视图 |
| 任意 | `enabled` 由假变真 | `closed`;代际 + 1、连错清零、清熔断字段;另清 `auto_disabled_*`(同今天) |

要点:

- **熔断从不修改 `enabled`**;`enabled` 由真变假、或 PUT 中 `enabled` 未变化(声明式同步的常态)都不触碰熔断态。
- 半开转换只发生在定时闸**全部放行**的锁内区域(`acquire_firing_slot` 的 `FOR UPDATE` 段,放在并发闸之后)。
  提交边界沿用执行器现状(`executors/scrapyd.py:105-132`,python_wheel 同构):
  ① 建单提交之前抛错(解析、选节点等)→ 半开转换、代际递增与任务一并回滚,调度仍为 `open`,下一次触发再试;
  ② 建单已提交(含 `no_target` 直接终态)→ 半开转换随之持久化;此后下发全部失败时执行器把任务标为
  `failed` / `dispatch_unavailable` 并抛 503,`dispatch_unknown` 时任务保持 `queued`——两种情况都已有试跑任务,
  后续触发按 `half_open` 跳过,不会重复放行,试跑结果由记录器照常处理(`dispatch_unavailable` 按上节判 `transient`)。
- trigger-now 不受熔断闸限制(手动始终可跑),其结果按上表参与(成功即恢复)。
- 状态机在 `_record_ledger` 现有的 schedule 行锁内执行(锁序不变);复位端点对 schedule 行 `FOR UPDATE` + 锁内重读后再写;
  `update_schedule` 在应用任何字段前先对 schedule 行 `FOR UPDATE` 并锁内重读(`populate_existing`),`enabled` 假→真的判断、
  当前代际读取与复位写入都基于锁内的行——并发的两次启用只复位一次;并发的启用与复位串行执行,后执行者按先执行者
  提交后的行判定(复位先:复位 + 1、启用再 + 1;启用先:启用 + 1 后状态已是 `closed`,复位无操作)。
- **不新增任何多行加锁路径**:定时闸、复位、`update_schedule` 各自只锁一条 schedule 行且不再持有其它行锁;
  模板更新不触碰调度行。因此不会与记录器「同一事务内按任务顺序依次锁多个 schedule」的既有做法成环。
- `record_task_outcomes` 改为返回本次**跳闸**(进入 `open` / `held`)的调度 id(测试与日志用),不再触发 reload。

### 3. 通知

`dedupe_key` 均为 `schedule.id`,沿用消息中心「未读期间合并、严重度只升不降」:

| 类型 | 严重度 | 时机 | payload |
|---|---|---|---|
| `schedule_breaker_open` | warning;24 小时升级时 error | 跳闸进入 `open`;升级时再发一次 | `schedule_id`、`schedule_name`、`consecutive_errors`、`threshold`、`retry_at`、`escalated` |
| `schedule_breaker_held` | error | 进入 `held` | `schedule_id`、`schedule_name`、`consecutive_errors`、`threshold` |
| `schedule_breaker_closed` | info | 由 `open` / `half_open` / `held` 恢复为 `closed`(复位与重启用除外——人为动作不通知) | `schedule_id`、`schedule_name`、`opened_at` |

**通知失败不影响记录**:每次熔断通知都包在 SAVEPOINT(`session.begin_nested()`)里调用,异常时只回滚该保存点并记
warning 日志——PostgreSQL 上失败语句会使整个事务进入中止态,仅靠 try/except(现有写法)无法再提交账本与熔断转换,
保存点把失败隔离在通知内部。`schedule_auto_disabled` 不再产生,前端保留其渲染以显示历史消息。

### 4. 配置(`[scheduler]`)

| 键 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `auto_disable_after_errors`(键名保留) | `DOPILOT_SCHEDULER_AUTO_DISABLE_AFTER_ERRORS` | 5 | 语义改为「熔断阈值」;0 = 永不跳闸 |
| `breaker_backoff_base_seconds` | `DOPILOT_SCHEDULER_BREAKER_BACKOFF_BASE_SECONDS` | 900 | ≥ 1 |
| `breaker_backoff_max_seconds` | `DOPILOT_SCHEDULER_BREAKER_BACKOFF_MAX_SECONDS` | 7200 | ≥ base;也是半开试跑期限 |
| `breaker_escalate_after_seconds` | `DOPILOT_SCHEDULER_BREAKER_ESCALATE_AFTER_SECONDS` | 86400 | ≥ 0;0 = 不升级 |

非法值(base < 1、max < base、escalate < 0)在加载配置时报错,server 不启动。

### 5. agent 与协议

- agent 在最后一个 stats 块内按 `'outcome/class':\s*'([^']+)'` 取值(与现有两键同一块、同一套「只认块内字典行」规则),
  UTF-8 容错解码,超过 64 字符截断;块外的同名文本不采信。
- `AgentEvent.outcome_class` 可选、默认 None。协议模型未设 `extra="forbid"`(`packages/protocol/dopilot_protocol/streams.py`
  无 `model_config`),新 agent → 旧 server 时该字段被忽略,旧 agent → 新 server 时为 None——**上线顺序无依赖**。
- server 收到非 None 值时落 `executions.outcome_class`(截断 64 字符)。

### 6. API 与 Web

- `ScheduleView` 增 `breaker_state`、`breaker_level`、`breaker_opened_at`、`breaker_retry_at`、`breaker_escalated_at`、
  `breaker_reason`、`breaker_artifact_id`;原 `auto_disabled_*` 字段保留(历史行仍可能有值)。
- 新端点 `POST /api/v1/schedules/{id}/breaker/reset` → 200 + `ScheduleView`;不存在 → 404 `schedule.not_found`;
  `closed` 态调用为无操作(见状态表),重复调用安全。不需要 reload 调度器。
- 调度页名称旁徽标(与现有「已自动禁用」徽标同位、同为截断 span 的兄弟节点):`open` →「熔断中」(tooltip:起始时间、
  下次试跑不早于);`half_open` →「试跑中」;`held` →「需人工」(destructive,tooltip:连错次数与起始时间)。
  行操作菜单在非 `closed` 时出现「复位熔断」,成功后 toast 并刷新列表。旧「已自动禁用」徽标逻辑保持。
- 铃铛:三个新类型按 i18n 渲染标题 / 正文,点击跳 `/schedules?highlight=<id>`。中英文案同步。

### 7. 迁移 0016

`schedules` 增 `breaker_state`(server default `'closed'`)、`breaker_level`(server default 0)及五个可空列;
`schedule_outcome_ledger.outcome_class`、`executions.outcome_class` 可空。存量行全部为 `closed`,
旧的 `enabled=false` + `auto_disabled_*` 行保持原样。downgrade 删除上述列。

### 8. 文档

- 新决策 0025:背景(引脱敏结论)、状态机、分类规则、通知、配置、与 0021 的关系(§6 的账本 / 代际保留,
  「达阈值 `enabled=false`」被取代)、后果(真坏但被误标 `transient` 的调度会持续失败试跑——退避等待最长 2 小时,
  实际间隔还受原触发周期与其它准入闸限制——并在 24 小时后升级)。
- 03 章节「任务结果记录与调度自动禁用」改为「任务结果记录与调度熔断」,并同步 06 中指向该锚点的链接;
  02 / 04 / 06 / README 按字段、配置、界面更新。

## 测试用例

命令约定:Python 用 `.venv/bin/python -m pytest`,PG 用例经 `env` 带本机 dev 库连接串(`docker-db-1`);
Web 用 `corepack pnpm --dir apps/web …`。全部经 `evidence.sh` 留证。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 实现完成 | `evidence.sh TC-01 -- .venv/bin/python -m pytest apps/agent/tests/test_scrapyd_stats.py -v` | 全部通过;新增断言覆盖:末块含 `'outcome/class': 'transient'` 取得该值;末块无该键 → None;**只有更早的块含该键**或**块外业务日志**打印该键 → None;超过 64 字符被截断;非 UTF-8 字节不抛错;原有两键解析不变 | evidence/TC-01.log,写法 (a) |
| TC-02 | A | 同上 | `evidence.sh TC-02 -- .venv/bin/python -m pytest apps/agent/tests -v -k outcome_class` | 全部通过且收集数 ≥ 3:scrapy 终态事件带 `outcome_class`;状态文件持久化该值且按状态文件重发的终态事件带同值;不含该字段的旧状态文件加载为 None | evidence/TC-02.log,写法 (a) |
| TC-03 | A | 同上 | `evidence.sh TC-03 -- .venv/bin/python -m pytest packages/protocol/tests/test_stream_schemas.py -v` | 全部通过;新增断言:带 / 不带 `outcome_class` 的 `AgentEvent` 均可解析,缺省为 None,序列化往返不丢值 | evidence/TC-03.log,写法 (a) |
| TC-04 | A | 同上 | `evidence.sh TC-04 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k classify` | 全部通过;分类矩阵:`log_flood` 且自报 `transient` → broken;`size-cap` 截断且自报 `transient` → broken;上限 > 0 时 `log_bytes` 恰等于上限且自报 `transient` → broken、低于上限 → 按自报 transient;上限为 0(关闭)时超大 `log_bytes` 的 failed + `transient` 与 `lost` 执行均为 transient;`lost` → transient;`dispatch_unavailable` / `dispatch_timeout` → transient;finished + ERROR + `transient` → transient;finished + ERROR + `broken` / `ok` / None / 未知值 → broken;无 stats 的 failed → broken;多执行一 broken 一 transient → broken;任务级:clean complete → ok,canceled / no_target → neutral | evidence/TC-04.log,写法 (a) |
| TC-05 | A | 同上 | `evidence.sh TC-05 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k event` | 全部通过:终态事件的 `outcome_class` 落到 `executions.outcome_class`;超长值截断为 64 字符;事件缺该字段时列保持 None | evidence/TC-05.log,写法 (a) |
| TC-06 | A | 同上 | `evidence.sh TC-06 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k trip` | 全部通过:5 次 transient → `open`、`enabled` 仍为真、`level=0`、`retry_at = now + 900s`、warning 通知 1 条;5 次 broken → `held` + error 通知;混合 → `open`;迁移前的 NULL 类出错行按 broken 计(4 条 NULL + 1 条 broken → `held`);4 次出错后 1 次 ok → 不跳闸且计数归零;阈值 0 → 永不跳闸;返回值为跳闸调度 id | evidence/TC-06.log,写法 (a) |
| TC-07 | A | 同上 | `evidence.sh TC-07 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k gate` | 全部通过:`open` 且未到点 → `fire_timer` 跳过、无新任务;到点 → 建任务、状态 `half_open`、任务代际 = 原代际 + 1、`retry_at = now + 7200s`;`half_open` 未过期限 → 跳过;过期限 → 再建试跑、代际不变、`retry_at` 顺延 7200s;`held` → 跳过;到点但被并发闸挡住 → 仍为 `open`、代际不变;`open` / `held` 下 trigger-now 照常建任务 | evidence/TC-07.log,写法 (a) |
| TC-08 | A | 同上 | `evidence.sh TC-08 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k half_open` | 全部通过:试跑 ok → `closed`、熔断字段清空、info 通知;试跑 transient 连续 4 次 → `retry_at` 依次为 now + 1800 / 3600 / 7200 / 7200 秒;试跑 broken → `held`;试跑 canceled 或 no_target → `open`、`level` 不变、`retry_at = now`;旧代际结果不改变状态;`open` 与 `held` 下当前代际 ok → `closed`;`open` 下当前代际出错 → 状态不变;**经真实 `record_task_outcomes`**:试跑 1 为 `lost` 且到期限仍未记录、已放行试跑 2(同代际)后,试跑 1 的 `lost` 结果被记录 → `open` 且 `level + 1`;`max_concurrency=0` 下试跑 1 超过期限仍在跑、试跑 2 已放行,试跑 1 随后成功被记录 → `closed` | evidence/TC-08.log,写法 (a) |
| TC-09 | A | 同上 | `evidence.sh TC-09 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k escalat` | 全部通过:`opened_at` 在 24 小时前、试跑 transient 失败 → `escalated_at` 被设、该调度的 `schedule_breaker_open` 通知严重度为 error 且 `escalated` 为真;再次试跑失败不再重复升级(`escalated_at` 不变);半开期限到点放行再试跑不触发升级;未满 24 小时不升级;升级阈值 0 → 永不升级 | evidence/TC-09.log,写法 (a) |
| TC-10 | A | 同上 | `evidence.sh TC-10 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k "reset or enable or artifact or view"` | 全部通过:`POST …/breaker/reset` 在 `open` / `half_open` / `held` 下 → `closed`、代际 + 1、计数 0、`enabled` 不变;在 `closed` 下 200 且代际与计数不变;未知 id → 404 `schedule.not_found`;`PUT enabled=false→true` 自 `open` → `closed`;`PUT enabled=true`(原本已真,模拟声明式同步)自 `open` / `held` → 状态不变;进入 `held` 时 `breaker_artifact_id` = 触发任务快照的制品 id;模板未换制品(或同一制品 id 重复 PUT)时 `held` 调度定时触发跳过;模板换新制品后下一次定时触发 → `half_open`、`level=0`、代际 + 1 并建试跑任务;模板 PUT 后调度行的熔断字段不变(模板服务不联动);**交错**:`held`(A)换制品 B → 试跑 B 进入 `half_open` → 模板再换制品 C → B 的试跑结果 `broken` 被记录 → `held` 且 `breaker_artifact_id = B` → 下一次定时触发放行 C 的试跑;`breaker_artifact_id` 为 NULL 的 `held` 调度换制品后仍跳过;`GET /schedules` 返回熔断字段与原 `auto_disabled_*` 字段 | evidence/TC-10.log,写法 (a) |
| TC-11 | A | 同上 | `evidence.sh TC-11 -- .venv/bin/python -m pytest apps/server/tests/test_config.py -v -k breaker` | 全部通过:默认值 900 / 7200 / 86400;三个环境变量覆盖生效;base 0、max < base、escalate −1 各自加载报错 | evidence/TC-11.log,写法 (a) |
| TC-12 | A | 同上;本机 PG(`docker-db-1`)可连 | `evidence.sh TC-12 -- env DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot .venv/bin/python -m pytest apps/server/tests/test_migration_0016_pg.py -v` | 全部通过(不得 skip):自 0015 升级,存量调度 `breaker_state='closed'`、`breaker_level=0`;预置的旧自动停用行(`enabled=false` + `auto_disabled_at`)原样保留;`breaker_state` 与 `breaker_level` 非空,其余新增列(含 `schedule_outcome_ledger.outcome_class`、`executions.outcome_class`)可空;downgrade 后新列消失,再 upgrade 成功 | evidence/TC-12.log,写法 (a) |
| TC-13 | A | 同 TC-12 | `evidence.sh TC-13 -- env DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker_pg.py -v` | 全部通过(不得 skip):到点的 `open` 调度(`max_concurrency=0`,排除并发闸的干扰)上两个并发 `fire_timer` 只产生 1 个试跑任务,调度为 `half_open`、代际只 + 1;对同一停用调度并发两次 `PUT enabled=true` → 代际只 + 1;`enabled=false` 的 `open` 调度上,用两个会话按确定顺序执行「复位」与「`PUT enabled=true`」(先执行者持锁未提交、后执行者阻塞,先执行者提交后放行):复位先 → 代际 + 2、启用先 → 代际 + 1,两种顺序终态均为 `closed` 且 `enabled` 为真;记录器事务把调度置为 `held(B)` 尚未提交时,另一会话把模板改为制品 C 并提交(不被阻塞),记录器随后提交,接着 `fire_timer` 建出试跑任务、调度为 `half_open`——反过来先提交记录器、后改模板,结论相同;同一模板下两个调度的结果在一个记录器事务内依次记录,期间另一会话更新该模板并提交,两边均在超时内完成、无死锁;通知故障注入(把 `notifications.notify` 替换为先执行一条必然出错的 SQL 再抛异常)下,`record_task_outcomes` 后提交成功,任务结果戳、账本行与熔断转换(`open`)均已持久化 | evidence/TC-13.log,写法 (a) |
| TC-14 | A | 同 TC-12 | `evidence.sh TC-14 -- env DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot .venv/bin/python -m pytest apps/server -q` | 全部通过,0 error、0 fail(含改写后的 `test_outcomes.py`、`test_reconcile_outcomes.py`) | evidence/TC-14.log,写法 (a) |
| TC-15 | A | 实现完成 | `evidence.sh TC-15 -- bash -c '.venv/bin/python -m pytest apps/agent packages/protocol -q && .venv/bin/ruff check apps packages'` | 两者均成功,exit 0 | evidence/TC-15.log,写法 (a) |
| TC-16 | A | 同上 | `evidence.sh TC-16 -- corepack pnpm --dir apps/web exec vitest run 'app/(app)/schedules/__tests__/schedules.test.tsx' components/layout/__tests__/notification-bell.test.tsx` | 全部通过;新增断言:`open` / `half_open` / `held` 三种徽标与 tooltip 文案;「复位熔断」仅在非 `closed` 时出现,点击调用复位 API 后刷新;旧「已自动禁用」徽标仍按 `auto_disabled_at` 显示;铃铛三个新类型渲染中文标题 / 正文且链接为 `/schedules?highlight=<id>` | evidence/TC-16.log,写法 (a) |
| TC-17 | A | 同上 | `evidence.sh TC-17 -- bash -c 'corepack pnpm --dir apps/web test && corepack pnpm --dir apps/web typecheck && corepack pnpm --dir apps/web lint && corepack pnpm --dir apps/web build'` | 四步均成功,exit 0 | evidence/TC-17.log,写法 (a) |
| TC-18 | A | 同上 | `evidence.sh TC-18 -- bash .ai/2026-11-03/schedule-circuit-breaker/evidence/docs-config-check.sh` | exit 0;脚本逐条断言:0025 存在且 README 有索引行;0021 有指向 0025 的说明;03 新章节标题存在,仓库内无指向旧锚点 `#任务结果记录与调度自动禁用` 的链接;04 含三个新键与环境变量;两份配置样例含三个新键;`loader.py` 含三个新环境变量映射;zh / en 文案都含三个新通知类型键 | evidence/TC-18.log,写法 (b) 断言脚本 |
| TC-19 | A | 同上 | `evidence.sh TC-19 -- bash -c 'python3 scripts/redaction/redact.py check --summary --files $(git ls-files -mo --exclude-standard)'` | exit 0、0 hit:本任务全部新增 / 修改文件(含任务目录与脱敏副本)无业务词 | evidence/TC-19.log,写法 (a) |
| TC-20 | A | 同 TC-01 | `evidence.sh TC-20 -- .venv/bin/python -m pytest apps/server/tests/test_schedule_breaker.py -v -k boundary` | 全部通过:到点的 `open` 调度上,① 让建单提交前的步骤抛错 → `fire_timer` 抛出后调度仍为 `open`、代际不变、无新任务;② 下发全部失败(假 dispatcher 拒收)→ 抛 503,任务已提交为 `failed` / `dispatch_unavailable`,调度为 `half_open`、代际 + 1;随即再次 `fire_timer` → 跳过、无第二个试跑;记录器处理该任务后 → `open` 且 `level + 1`(按 transient,非 `held`) | evidence/TC-20.log,写法 (a) |

## 风险与回滚

- **真坏却被标 `transient`**:会持续失败试跑(退避等待最长 2 小时,实际间隔还受原触发周期与其它准入闸限制),靠 24 小时升级 error 兜底;分类错误由爬虫侧修正。
- **试跑长期无结果**:如 `lost` 结果要等 `lost_outcome_grace_seconds`(默认 24 小时)才记录。半开期限(= 退避上限)
  到点后在下一次原定触发放行新试跑(仍受其它准入闸限制),不会卡死;再试跑共享代际,迟到结果照常计入。
- **中性结果让试跑反复**:无可用节点时每次触发都会立即重试试跑,与今天「无节点照常每次触发」的频率相同,不放大负载。
- **严重度只升不降**:同一调度未读的 `schedule_breaker_open` 若已升级为 error,下次熔断合并进同一行时仍显示 error——
  消息中心既有语义,读后即新起一行。
- **语义变化**:`auto_disable_after_errors` 不再禁用调度;依赖「出错即 `enabled=false`」的外部脚本(本仓库外)会看到
  `enabled` 保持为真。决策 0025 与配置说明写明。
- **上线顺序**:两侧独立;dopilot 先上时缺键按 broken,与今天同口径(只是不再改 `enabled`,改为进入 `held`)。
- **回滚**:镜像回滚前先执行 0016 downgrade(删除熔断列,调度回到「仅 `enabled`」语义);熔断中的调度回滚后立即恢复
  按 `enabled` 触发。旧镜像会重新启用 `enabled=false` 式自动停用。
