---
status: approved
task: fix-outbox-sent-oom
date: 2026-08-26
approved_at: 2026-08-26T02:15+08:00(用户预先豁免确认闸,见「用户授权记录」)
plan_review_max_rounds: 15
impl_fix_max_rounds: 15
---

# 方案:修复 command_outbox sent 行无界加载导致的 server OOM 重启循环

## 用户授权记录(轮次上限与确认闸)

2026-08-26 用户在会话中明确指示(原文):

> "plan 和改修的 review 最大 15 轮。做到 push 为止,plan 不需要找我确认。"

据此:frontmatter 写入 `plan_review_max_rounds: 15` 与 `impl_fix_max_rounds: 15`
(覆盖默认 3,属用户明确要求的放宽);plan 人工确认闸由用户预先豁免——
plan 评审 pass 后直接置 `status: approved` 进入实现;收尾包含 commit + push
(用户已明确授权)。以上将在实现记录与汇报中再次声明。

## 背景与目标

生产事故(2026-08-25 09:42 起):server 容器每 ~21 秒被 cgroup OOM 杀死
(内核日志 803 次 `Memory cgroup out of memory: Killed process (dopilot-server)`),
根因链:

1. `command_outbox` 的 `sent` 行设计上永不清理("a sent row normally stays
   sent forever",apps/server/dopilot_server/redis/dispatcher.py:180),生产
   累积 424,279 行(2026-07-27 起,~14k/天);
2. `CommandDispatcher.reconcile_sent_once`(dispatcher.py:200)执行
   `select(CommandOutbox).where(status=='sent', updated_at<cutoff)` **无
   LIMIT、无任务活跃度过滤**,把全部 sent 行物化为 ORM 对象;
3. dispatcher 启动后第一个 tick 必跑该查询(`_last_sent_reconcile is None`
   即视为到期,dispatcher.py:259),~10 秒内内存 15MiB → 2GiB(compose 限额),
   OOM → 重启 → 死循环。被杀的是子进程,PID 1(docker-init)退出码 0,
   docker 层面 `OOMKilled=false`,不易察觉。

任务终态后其 outbox 行对 reconcile 已无意义(现行代码逐行跳过终态任务,
dispatcher.py:214-216),却仍被整表加载 —— 这是本次要修的核心。

目标(两层):
- **有界化**:reconcile 与 dispatch tick 的 outbox 查询在 SQL 侧过滤 + 限批,
  且限批扫描**跨周期推进、可回绕**(不产生饥饿),内存占用与表规模解耦;
- **可清理**:已解决(sent/failed/canceled)的 outbox 行在**不触碰持久
  reclaim 去重事实与软终态(lost)任务**的前提下进入自动保留清扫
  (RetentionSweepLoop),表规模有上界。

生产止血(停容器 + 手工 DELETE 终态任务的 sent 行 424,277 条 + VACUUM)已在
任务外单独执行完毕,不属于本方案改动。

## 改动范围

预计触及 13 个文件(> 10,须过 plan 评审闸):

| 文件 | 改动 |
|---|---|
| `apps/server/dopilot_server/redis/dispatcher.py` | `reconcile_sent_once` 查询 JOIN tasks 过滤活跃任务 + keyset 游标限批(页尾快照、空页同轮回绕,见实现方案 §1);`_tick` 的 dispatchable 查询加 `ORDER BY created_at` + 限批(构造参数 `dispatch_batch_limit`,默认 1000) |
| `apps/server/dopilot_server/services/maintenance.py` | 新增 `prune_resolved_outbox()`:分批删除已解决 outbox 行,**排除 reclaim 行与活跃/lost 任务的行**(见实现方案 §3;批删模式照抄 `prune_event_audit`,maintenance.py:557) |
| `apps/server/dopilot_server/retention.py` | `sweep_once` 新增独立守护的一步,调用 `prune_resolved_outbox` |
| `apps/server/dopilot_server/config/settings.py` | `RedisSettings.sent_reconcile_batch_limit=500`;`MaintenanceSettings.outbox_retention_days=7`、`outbox_delete_batch=5000` |
| `apps/server/dopilot_server/config/loader.py` | 上述 3 个新键的 TOML/env 映射(`DOPILOT_` 前缀,循现有映射表) |
| `configs/server.example.toml` | 新键示例与注释 |
| `configs/server.docker.toml` | 新键示例 |
| `apps/server/tests/test_log_guard.py` | reconcile 有界化 + 游标推进/回绕用例(TC-01、TC-02、TC-09) |
| `apps/server/tests/test_dispatcher.py` | dispatch tick 限批用例(TC-07) |
| `apps/server/tests/test_maintenance.py` | prune 用例 + 排除边界 + sweep 接线/故障隔离 + reclaim 不变量回归(TC-03/04/05/10/11/12) |
| `apps/server/tests/test_config.py` | 新配置默认值/TOML/env 覆盖(TC-06) |
| `docs/architecture/04-configuration.md` | `[redis]`/`[maintenance]` 配置表补新键 |
| `docs/architecture/03-execution-and-logs.md` | reclaim 持久去重段落补一句:outbox 保留清扫永不删除 `stop(intent=reclaim)` 行,该事实与任务同寿命 |

明确不动:
- `command_outbox` 表结构与 Alembic 迁移(无 schema 变更、不加索引:reconcile
  查询经 tasks 活跃行驱动 + `command_outbox.task_id` 已有索引,规模有界后
  顺序批删足够);
- `cleanup_terminal_data` 既有的"随任务删 outbox"路径(保留,是 reclaim 行
  与 lost 任务行的最终清理出口);
- outbox 行的创建/取消/coalesce 语义(services/outbox.py),尤其
  `reclaim_ever_issued` 的 status-blind 语义(outbox.py:166-183);
- decision 0008(at-least-once)与 0019(资源硬上限)结论——本方案是其延伸,
  不新开 decision。

## 实现方案

### 1. reconcile_sent_once 有界化 + keyset 游标(dispatcher.py)

**排序、游标与 sweep 边界**:按 `(updated_at, command_id)` 稳定排序;dispatcher
实例持有两个内存态:游标
`self._sent_reconcile_cursor: tuple[datetime, str] | None` 与本轮 sweep 的
**高水位边界** `self._sent_reconcile_hwm: datetime | None`。每轮:

1. **sweep 开始时(游标为 None)冻结边界**:`hwm = cutoff`(= 本次调用的
   `now - min_age`)。本 sweep 的每一页都只查 `updated_at < hwm` 的行——
   sweep 进行期间新到/新满足 cutoff 的行(键必然更晚)被边界排除,留给下一
   sweep,**扫描终点不会被后来写入持续推远**(第 4 轮评审 R-01:若无冻结
   边界,持续写入使查询永远满批、游标永不回绕,已扫过而事后被裁剪的旧行
   将永久失去复查机会);
2. 按(游标, hwm)查一页(≤ batch 行);
3. **SELECT 返回后、任何 await/修改/flush 之前**,立即把页尾快照为不可变元组
   `page_end = (rows[-1].updated_at, rows[-1].command_id)`(`updated_at` 带
   `onupdate=func.now()`,逐行处理中的 requeue 与 `notif.notify` 触发的 flush
   会改写 ORM 行上的值,绝不能事后从 ORM 行取键——否则游标越过未扫描的旧行
   形成饥饿);
4. 逐行处理(现有逻辑不变);
5. 游标推进:满批 → `cursor = page_end`;不满批 → `cursor = None`、
   `hwm = None`(本 sweep 扫尾,下轮开新 sweep);
6. **空页回绕**:若本页为空且游标非 None(游标已达本 sweep 边界),置
   `cursor = None`、**冻结新边界 `hwm = cutoff`**,并**同一调用内从头重查
   一次**(至多重查一次,不成环),再按 3-5 处理。

覆盖上界:每个 sweep 的扫描集在开始时被边界冻结(设其行数为 N_sweep),
无论期间写入多少新行,该 sweep 必在 `ceil(N_sweep/batch)` 次调用内完成并
回绕;任一丢失消息最迟在"当前 sweep 剩余页数 + 下一 sweep 定位到该行"
即 ≤ `2·ceil(N/batch)+1` 个 `sent_reconcile_interval_seconds` 周期内被检查
(N = 活跃任务 sent 行总数,与写入速率无关)—— 守住 decision 0008 的
at-least-once。

```python
cutoff = now - timedelta(seconds=min_age)
batch = max(1, self._settings.redis.sent_reconcile_batch_limit)
if self._sent_reconcile_cursor is None:
    self._sent_reconcile_hwm = cutoff           # sweep 开始:冻结边界

def _page_stmt(cursor, hwm):
    stmt = (
        select(CommandOutbox)
        .join(Task, Task.id == CommandOutbox.task_id)
        .where(
            CommandOutbox.status == OUTBOX_SENT,
            CommandOutbox.updated_at < hwm,     # 冻结的 sweep 边界(≤ cutoff)
            Task.status.in_(tuple(states.TASK_ACTIVE)),
        )
        .order_by(CommandOutbox.updated_at, CommandOutbox.command_id)
        .limit(batch)
    )
    if cursor is not None:
        stmt = stmt.where(
            tuple_(CommandOutbox.updated_at, CommandOutbox.command_id)
            > tuple_(*cursor)
        )
    return stmt

rows = (await session.execute(
    _page_stmt(self._sent_reconcile_cursor, self._sent_reconcile_hwm)
)).scalars().all()
if not rows and self._sent_reconcile_cursor is not None:
    # 本 sweep 扫尾:同轮回绕,开新 sweep(冻结新边界)重查一次
    self._sent_reconcile_cursor = None
    self._sent_reconcile_hwm = cutoff
    rows = (await session.execute(_page_stmt(None, cutoff))).scalars().all()
page_end = (
    (rows[-1].updated_at, rows[-1].command_id) if len(rows) == batch else None
)   # ← 处理前快照;不满批置 None(扫尾)
# ... 逐行处理(现有逻辑)...
self._sent_reconcile_cursor = page_end
if page_end is None:
    self._sent_reconcile_hwm = None
```

- 语义不变:现行代码本就逐行跳过终态/缺失任务,过滤只是提前到 SQL 侧;
  逐行的 `svc.get_task` 复查保留(防查询后任务并发终态化的竞态);
- `tuple_` 行值比较 PostgreSQL 与 SQLite(≥3.15,aiosqlite 测试环境)均支持;
- 游标仅存内存:进程重启后从头扫;活跃 sent 行规模受 coalesce 约束,实际
  一两页即覆盖,不引入持久化游标的复杂度;
- `Task` 自 `..models.execution` 导入,`tuple_` 自 `sqlalchemy` 导入。

### 2. dispatch tick 限批(dispatcher.py)

`_tick` 的 `OUTBOX_DISPATCHABLE` 查询加 `ORDER BY created_at ASC` +
`LIMIT self._dispatch_batch_limit`(构造参数,默认 1000)。正常规模(coalesce
约束下 pending 仅百级)不受影响,仅作 Redis 长期不可用等极端场景的安全网。
此处 FIFO 无饥饿问题:与 reconcile 不同,dispatchable 行每次处理必然发生
状态迁移(sent / failed_retryable→retry_count 递增→give-up),不会有"检查后
原地不动"的行反复占住窗口;失败重试行也受 give_up_at 兜底。

### 3. prune_resolved_outbox(services/maintenance.py)

```python
RESOLVED = (OUTBOX_SENT, OUTBOX_FAILED, OUTBOX_CANCELED)
UNSAFE_TASK = tuple(states.TASK_ACTIVE) + (states.TASK_LOST,)
# while 循环,每批:
ids = select(CommandOutbox.command_id).where(
    CommandOutbox.status.in_(RESOLVED),
    CommandOutbox.updated_at < now - timedelta(days=outbox_retention_days),
    # 持久 reclaim 去重事实(outbox.py reclaim_ever_issued 为 status-blind):
    # stop(intent=reclaim) 行终生保留,只随任务删除(cleanup_terminal_data)
    ~((CommandOutbox.type == "stop") & (CommandOutbox.intent == "reclaim")),
    # 父任务活跃或 lost(软终态,可被后到 agent 事件覆盖/复活)→ 不删;
    # 仅父任务硬终态(complete/failed/canceled/no_target)或任务行已删(孤儿)
    ~exists().where(
        (Task.id == CommandOutbox.task_id) & Task.status.in_(UNSAFE_TASK)
    ),
).limit(outbox_delete_batch)
# delete WHERE command_id IN ids;每批 commit;不足一批即止;返回总数
```

安全边界(为什么这样定):

- **reclaim 行无条件排除**:`reclaim_ever_issued`(outbox.py:166)刻意
  status-blind(sent 甚至 failed 都算数),heartbeat 对 EXEC_LOST 的
  at-most-once reclaim(events.py:217)与 `finalize_drained_logs` 对
  server-lost 执行的日志定稿门禁(redis/reconcile.py:242)都依赖该行存在。
  outbox 默认保留 7 天 < 任务保留 30 天,若删掉,后到 heartbeat 会重复
  reclaim、日志门禁误开。reclaim 行每 execution 终生至多一条(at-most-once
  不变量自身保证),体量可忽略,留到随任务删除;
- **lost 任务的行整体排除**:`TASK_LOST` 是软终态(states.py:199 允许被后到
  agent 事件覆盖),其行走"随任务删除"路径,不参与提前清扫;
- **`OUTBOX_UNRESOLVED` 三态(pending/dispatching/failed_retryable)不在
  RESOLVED 白名单**,无论多老、父任务何状态,一律不删(在途命令安全);
- `outbox_retention_days=0` 关闭(循 `event_audit_retention_days` 惯例);
- 时间列用 `updated_at`(行到达终态的时刻)。

### 4. 清扫接线(retention.py)

`sweep_once` 在 event_audit 步骤(step 2)后插入 outbox 步骤,独立
`async with session` + try/except 守护,失败仅 `logger.error` + rollback,
不影响其余步骤(与 step 2/4/6/7 完全同构)。

### 5. 配置与文档

- settings.py 三个新字段带注释(默认 500 / 7 / 5000);
- loader.py 按现有映射表加 `DOPILOT_REDIS_SENT_RECONCILE_BATCH_LIMIT`、
  `DOPILOT_MAINTENANCE_OUTBOX_RETENTION_DAYS`、
  `DOPILOT_MAINTENANCE_OUTBOX_DELETE_BATCH`(以 loader 实际命名规则为准);
- 两份 configs 样例、docs/architecture/04-configuration.md 配置表同步;
- docs/architecture/03-execution-and-logs.md 的 reclaim 持久去重段落补一句
  "outbox 保留清扫永不删除 reclaim 行"(与代码同一提交)。

## 测试用例

证据契约(对每条 A 档用例统一适用,落盘至任务目录 `evidence/`):
**执行命令原文 + 完整 stdout/stderr + 退出码**,一条用例一个文件
`evidence/tc-NN.txt`(内容:第一行命令,随后全量输出,末行 `exit=<code>`);
TC-08 全量回归的证据独立落盘 `evidence/tc-08-ruff.txt` 与
`evidence/tc-08-pytest.txt`,**不替代**各用例自身证据。

**SQL 侧断言技法**(TC-01/02/07 共用,锁定"过滤与限批发生在数据库查询自身、
而非全量加载后 Python 侧切片"):测试经
`sqlalchemy.event.listen(engine.sync_engine, "before_cursor_execute", hook)`
捕获被调用期间实际下发的 SQL 语句与参数,对涉及 `command_outbox` 的 SELECT
断言语句文本包含相应 JOIN/谓词/LIMIT/ORDER BY(大小写不敏感匹配),并核对
LIMIT 参数值。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | fakeredis + sqlite 会话;2 条 sent 行消息已从流中消失:1 条父任务 running、1 条父任务 complete;`before_cursor_execute` 钩子捕获 SQL | `pytest apps/server/tests/test_log_guard.py -k <TC01测试名>` | 返回仅含活跃任务那条 command_id;终态任务行保持 `sent` 不被重排;**SQL 断言**:reconcile 的 command_outbox SELECT 语句文本含 tasks JOIN、活跃状态谓词与 LIMIT(过滤发生在 SQL 侧,非加载后跳过) | `evidence/tc-01.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-02 | A | `sent_reconcile_batch_limit=2`;3 条活跃任务 sent 行、消息均已消失,seed 的 (updated_at, command_id) 取已知固定值;`before_cursor_execute` 钩子捕获 SQL | `pytest ... -k <TC02测试名>`:连续调用 `reconcile_sent_once` | 第一次恰好重排 2 条((updated_at,command_id) 序最前),且**首轮结束后直接断言 `dispatcher._sent_reconcile_cursor` 等于 seed 的原始页尾元组 `(ts2, id2)`**(flush 后才取页尾的错误实现会得到被 onupdate 改写的新时间戳而失败——杀死 R-02 游标污染缺陷);第二次收尾第 3 条;**SQL 断言**:两次 SELECT 均含 LIMIT 且参数值为 2 | `evidence/tc-02.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-03 | A | seed:硬终态任务的 sent/failed/canceled 旧行各 1、孤儿行(无 task)1,`outbox_delete_batch=2` | `pytest apps/server/tests/test_maintenance.py -k <TC03测试名>` | 4 行全删(跨 2 批),返回 4 | `evidence/tc-03.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-04 | A | seed(参数化,逐一覆盖 `OUTBOX_UNRESOLVED` 全集):硬终态任务的 pending / dispatching / failed_retryable 旧行;另 seed 活跃任务的 sent 旧行、硬终态任务的 sent 新行;再跑一组 `outbox_retention_days=0` | `pytest ... -k <TC04测试名>`(参数化 3 态) | unresolved 三态无论多老均保留;活跃任务行、窗口内新行保留;retention=0 时返回 0 且不删任何行 | `evidence/tc-04.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-05 | A | RetentionSweepLoop + seed 硬终态任务旧 sent 行 | `pytest ... -k <TC05测试名>`:调 `sweep_once` | outbox 行被删(新步骤已接线),其余步骤照常完成 | `evidence/tc-05.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-06 | A | 无配置 / TOML 覆盖 / env 覆盖三种加载 | `pytest apps/server/tests/test_config.py -k <TC06测试名>` | 3 个新键默认 500/7/5000,TOML 与 env 均可覆盖 | `evidence/tc-06.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-07 | A | `dispatch_batch_limit=2`,seed 3 条 pending 行;`before_cursor_execute` 钩子捕获 SQL | `pytest apps/server/tests/test_dispatcher.py -k <TC07测试名>`:跑一次 `_tick` | 恰好 2 条被 XADD(created_at 最老优先),第 3 条仍 pending;再 tick 收尾;**SQL 断言**:dispatchable SELECT 语句文本含 ORDER BY created_at 与 LIMIT 且参数值为 2(限批在 SQL 侧生效) | `evidence/tc-07.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-08 | A | 全量回归 | `ruff check apps packages` + `python -m pytest apps/server`(含既有 `test_sent_reconcile_requeues_vanished_commands` 等) | 全部通过,退出码 0 | `evidence/tc-08-ruff.txt`、`evidence/tc-08-pytest.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-09 | A | 饥饿回归(含持续写入):`sent_reconcile_batch_limit=1`;初始 2 条活跃任务旧 sent 行:X((updated_at,command_id) 序最前)消息**仍在流中**,Y 消息已丢失;对 `fake.xrange` 打点记录被查询的 (stream, msg_id) | `pytest ... -k <TC09测试名>`:连续调用 `reconcile_sent_once`;**每次调用之间插入一条键更晚且已满足 cutoff 的新活跃 sent 行(Z1、Z2,消息已丢失),并在第 2 次调用后把 X 的消息从流中删除**(模拟首查存在、随后被裁剪) | 第 1 次:sweep 边界冻结为 {X,Y},xrange 打点含 X、返回 [](X 原地不动,游标推进);第 2 次:返回 [Y](调用间插入的 Z1 键在边界外,不占用本 sweep 窗口);第 3 次:游标达本 sweep 边界 → 空页同轮回绕开新 sweep(边界覆盖 X/Z1/Z2),xrange 打点再次含 X 且 X 被重排,返回 [X](**持续写入下旧行仍被回绕复查并重排**——杀死"满批永不回绕"的饥饿实现);第 4 次:返回 [Z1](新行按序被后续页覆盖) | `evidence/tc-09.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-10 | A | 故障隔离(双向):(a) monkeypatch `prune_resolved_outbox` 抛异常;(b) monkeypatch 前置步骤 `prune_event_audit` 抛异常 + seed 硬终态任务旧 sent 行 | `pytest ... -k <TC10测试名>`:各调一次 `sweep_once` | (a) 后续步骤(如 notification prune)仍执行、sweep 不中断;(b) outbox 清扫仍执行、行被删 | `evidence/tc-10.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-11 | A | 排除边界:seed 硬终态任务的旧 `stop(intent=reclaim)` 行(sent 与 failed 各 1)、`TASK_LOST` 任务的旧 sent run 行、孤儿 reclaim 行(无 task) | `pytest ... -k <TC11测试名>`:调 `prune_resolved_outbox` | reclaim 行(含孤儿)与 lost 任务行全部保留,返回值不含它们;普通硬终态旧行正常删除 | `evidence/tc-11.txt`:命令 + 完整 stdout/stderr + 退出码 |
| TC-12 | A | reclaim 不变量回归:seed `EXEC_LOST` 执行 + 其父任务、已存在的旧 `stop(intent=reclaim)` sent 行;跑 `prune_resolved_outbox` 后:(a) 构造 heartbeat 事件走 events 处理路径;(b) 调 `finalize_drained_logs` 场景 | `pytest ... -k <TC12测试名>` | 清扫后 reclaim 行仍在,`reclaim_ever_issued` 保持 True;(a) heartbeat 不再新建 reclaim 行(全表 stop/reclaim 行数不变);(b) 日志定稿门禁判定与清扫前一致(reclaimed-lost 可定稿) | `evidence/tc-12.txt`:命令 + 完整 stdout/stderr + 退出码 |

(无 C 档用例;TC-01/02/04/09/10/11/12 覆盖异常与边界路径:终态过滤、批界、
unresolved 保留、饥饿回归、故障注入、reclaim/lost 排除、不变量回归。)

## 风险与回滚

- **行为变化 1**:sent 行不再永久保留(默认 7 天后随硬终态任务清理;reclaim
  行与 lost 任务行除外,仍与任务同寿命)。audit 需求由 `event_audit` 与
  `tasks`/`executions` 承担;若需恢复旧行为,设 `outbox_retention_days=0`
  即回到"只随任务删除"(rollback 开关)。
- **行为变化 2**:流被清空后的 sent 重排不再单次全量,而是每
  reconcile 周期一批(默认 500/300s),keyset 游标 + 冻结 sweep 边界 + 空页
  回绕保证全表轮转覆盖(上界 `2·ceil(N/batch)+1` 个周期,与写入速率无关)。
  极端大积压时收敛变慢,但 at-least-once 语义不变;必要时调大
  `sent_reconcile_batch_limit`。
- **游标与 sweep 边界为内存态**:进程重启后从头扫描并冻结新边界。活跃 sent
  行规模受 coalesce 约束,实际一两页即覆盖;不引入持久化游标的复杂度。空页
  回绕同一调用内至多重查一次,不成环;sweep 边界在 sweep 开始时冻结,持续
  写入不会推远扫描终点(第 4 轮评审 R-01)。
- **游标污染防护**:页尾键在 SELECT 后、任何处理/flush 前快照为不可变元组
  (`updated_at` 带 onupdate,事后从 ORM 行取键会拿到被改写的值,导致越页
  饥饿 —— 评审 R-02 场景),实现与 TC-02/09 双向锁定该行为。
- **竞态**:查询后、处理前任务终态化 —— 保留逐行 `svc.get_task` 复查,语义
  与现行一致;prune 侧 RESOLVED 白名单 + reclaim/lost 排除 + NOT EXISTS
  活跃或 lost 任务,`OUTBOX_UNRESOLVED` 在途行与持久去重事实绝不会被删。
- **回滚**:纯代码回退即可,无 schema/迁移;新配置键均有默认值,旧 TOML
  无需改动即可运行。
- **部署注意**:修复上线前生产已手工清过表(424,277 行已删,表 407MB→192kB;
  按新边界复核:被删行均为 sent+run 型、父任务硬终态,不含 reclaim 事实行
  ——生产 reclaim 行若曾存在也属 stop 型,需在上线后观察;风险已发生不可逆,
  但 heartbeat 重复 reclaim 的后果是幂等回收指令重发一次,agent 侧幂等,
  可接受);其他部署未清的,首次 sweep 会分批删历史行(每批 5000 + commit,
  不长锁)。
