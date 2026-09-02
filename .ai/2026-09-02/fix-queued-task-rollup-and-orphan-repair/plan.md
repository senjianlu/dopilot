---
status: approved
task: fix-queued-task-rollup-and-orphan-repair
date: 2026-09-02
approved_at: 2026-09-02T11:50+08:00
plan_review_max_rounds: 15
impl_fix_max_rounds: 15
---

# 方案:修复 queued task 在 execution 直达终态时永久卡住,并加 task 级对账自愈

## 用户授权记录(轮次上限)

2026-09-02 用户在会话中明确指示(原文):

> "确认要修,数据也要修正,全部你来帮我处理。plan 和改修的 review 均最大 15 轮。"

据此:frontmatter 写入 `plan_review_max_rounds: 15` 与 `impl_fix_max_rounds: 15`
(覆盖默认 3,属用户明确要求的放宽)。本方案预计触及 8 个文件(≤ 10),
plan 评审闸按规则不强制,但用户已为 plan 评审指定轮次上限,故**仍执行
plan 评审**。plan 人工确认闸**未被豁免**:评审 pass 后向用户呈现摘要,
用户确认后才置 `approved`。commit 仍需用户确认(AGENTS.md 通用硬规则)。

## 背景与目标

### 生产现场(2026-09-02 经 Web API 只读核实)

生产 `GET /api/v1/tasks?status=queued` 有 2 条任务停在 `queued` 已 7 天:

| task | schedule | created_at(UTC) | execution |
|---|---|---|---|
| `6044a26b408944b5bda81e90b4e48fca` | LOOTFARM 730(`* * * * *`) | 2026-08-25 22:22:00 | 1 条,`finished`,`started_at == finished_at == 22:22:21`,`remote_job_id` 为空 |
| `d1d2c9ae7ec948de84282c80bf04ccae` | MARKETCSGO 730(`* * * * *`) | 2026-08-25 22:22:00 | 同上(agent-01) |

两条 task 的 `started_at` 均为空。创建时间处于 2026-08-26 outbox OOM 事故
窗口(server 每 ~21s 被 OOM 杀一次;`.ai/2026-08-26/fix-outbox-sent-oom`),
execution 终态时间恰好落在一个重启周期上。

### 根因(代码层,HEAD 仍存在)

1. server 对该 execution 应用的**第一条**事件就是终态 `finished`(中间的
   `running` 事件在事故窗口丢失)。`_apply_status` 对终态有
   `started_at is None → started_at = now` 兜底
   (`apps/server/dopilot_server/services/events.py:89-90`),所以 execution
   侧 `started_at == finished_at`。
2. `_update_task` 只在 `execution.status == EXEC_RUNNING` 时把 queued task
   收敛到 running(`services/events.py:156-159`);终态事件不触发收敛。
3. roll-up 算出 `complete`,但 task 状态机 `_TASK_EDGES[queued]` 只有
   `queued/running/failed/canceled/lost`,**没有 `complete`**
   (`services/states.py:129-131`),`is_valid_task_transition("queued","complete")`
   为 False,roll-up 被拒绝,task 永久停在 `queued`。
4. 对账循环 `reconcile_once` 只遍历**活动态 execution**
   (`redis/reconcile.py:139-150`);该 task 的 execution 已终态,对账永远看不见它。
   现有三层兜底(outbox 900s give-up、心跳超时、事件停滞)都作用于活动态
   execution 或未投递命令,对"execution 已终态但 task 未 roll-up"这类**task
   级不一致**没有任何出口,只能人工 `mark-lost`。

execution 侧 `pending → finished/failed/canceled/lost` 是合法转换
(`states.py:170-179`),task 侧却跟不上——这是状态机的缝。

### 与并发上限升级的关系

决策 0022(`docs/decisions/0022-schedule-concurrency-limit.md`)的并发闸按
`TASK_ACTIVE`(queued/running/finalizing)计数。升级后存量调度
`max_concurrency` 回填为 1,这两条卡住的 queued 任务会让 LOOTFARM 730 与
MARKETCSGO 730 **永久无法触发**。因此本修复须先于生产升级落地,且升级后
存量数据须自动修正。

### 目标

1. **根因修复**:execution 从 pending 直达任一非 pending 状态(running 或
   终态)时,仍为 queued 的 task 先收敛到 running(补 `started_at`),再做
   roll-up。不放宽 task 状态机(queued 仍不可直达 complete/finalizing)。
2. **task 级对账自愈**:`reconcile_once` 增加一趟"活动态 task 且名下无活动
   execution"的扫描——executions 全终态 → 收敛 + roll-up 到真实终态;零
   execution 且超过阈值 → 置 `lost`。升级后第一个对账 tick(≤ 5s)即修正
   生产两条存量数据,且堵住未来任何来源的同类不一致(不只是本次的事件丢失
   路径)。
3. **不做**泛化的"queued 超时抛弃"定时器:未投递有 900s give-up、pending
   有心跳/停滞兜底,再加一层按时长抛弃会与 at-least-once 重投语义冲突。

### 存量数据修正路径(用户要求"数据也要修正")

不手工改生产数据库、不用 `mark-lost`(会把真实已 finished 的任务记成
lost,失真且触发 0021 的错误计数)。路径:本任务合入 → CI 构建
`rabbir/dopilot-with-deps` → 生产升级 → 新 server 启动后 `RedisReconcileLoop`
首个 tick 把两条任务 roll-up 为 `complete`(`started_at`/`finished_at` 取自
execution),同 tick 内 `record_task_outcomes` 记录非错误结果。升级后验证
步骤见「风险与回滚」。

## 改动范围

预计触及 8 个文件(≤ 10):

| 文件 | 改动 |
|---|---|
| `apps/server/dopilot_server/services/executions.py` | 新增纯内存 helper `converge_task(task, executions, now) -> bool`:task 为 queued 且任一 execution 已离开 pending → task 置 running、`started_at` 取已开始 executions 的最早 `started_at`(缺失则 `now`)。供事件消费与对账共用 |
| `apps/server/dopilot_server/services/events.py` | `_update_task`:先 `list_executions`,用 `converge_task` 取代现有"仅 running 事件收敛"的分支,再做既有 roll-up(含 lost 重滚与 `outcome_recorded_at` 复位逻辑不变) |
| `apps/server/dopilot_server/redis/reconcile.py` | `ReconcileReport` 增 `orphan_rolled_up` / `orphan_lost` / `repaired_task_ids`;新增 `repair_orphaned_tasks(session, settings, *, now)`(见实现方案 §2),由 `reconcile_once` 在 execution 循环之后调用并合并到 report |
| `apps/server/tests/test_event_consumer.py` | TC-01 ~ TC-06:终态直达的收敛与 roll-up、多 execution 扇出、既有路径回归 |
| `apps/server/tests/test_reconcile_redis.py` | TC-07 ~ TC-12:对账自愈的选择谓词、roll-up 语义、零 execution 阈值、幂等、终态不选、与结果记录同 tick 联动 |
| `apps/server/tests/test_reconcile_orphans_pg.py`(新) | TC-13、TC-14:PostgreSQL 真实 `NOT EXISTS` + `FOR UPDATE` 路径与并发终态写入者互斥 |
| `docs/architecture/03-execution-and-logs.md` | 「状态事件与对账」补两条:收敛条件改为"execution 离开 pending";task 级孤儿修复 |
| `.ai/2026-09-02/fix-queued-task-rollup-and-orphan-repair/*` | 本任务过程产物 |

明确不动:

- `services/states.py` 的 `_TASK_EDGES` / `_EXEC_EDGES`:不给 queued 加
  `complete` 边(`test_states.py:46-47` 明示 queued 不得跳转 finalizing 的
  设计意图,本方案沿用"必经 running"的口径);
- `maintenance.mark_task_lost`(人工兜底保留,零 execution 强制置 lost 的
  语义与本方案对齐);
- `reconcile._rollup`(仅服务于 `mark_lost`,目标 `lost` 从 queued 可达,无需
  收敛);
- outbox / dispatcher / 并发闸(0022)/ 结果记录(0021)的既有逻辑;
- Alembic:无 schema 变更、无数据迁移(自愈由运行期对账完成,不做一次性
  迁移脚本——迁移只跑一次,对账持续生效且同样修正本次两条);
- Web 前端:task 状态展示无需改动(`status_detail` 前端不渲染,仅 API 可见);
- 不新增 decision:本方案是 0021/0022 所依赖的状态机一致性修复,不改变
  已确认决策。

## 实现方案

### 1. 事件消费收敛(services/executions.py + services/events.py)

`services/executions.py` 新增:

```python
def converge_task(task: Task, executions: list[Execution], now: datetime) -> bool:
    """queued task -> running once ANY execution has left ``pending``.

    Covers the dispatch_unknown path (a ``running`` event) AND a terminal that
    arrives without a preceding ``running`` (event lost, 2026-08-26 incident):
    the task state machine requires queued -> running before any roll-up to
    ``complete``. ``started_at`` = earliest started execution (fallback ``now``).
    Pure in-memory; the caller holds the task row lock and commits.
    """
    if task.status != states.TASK_QUEUED:
        return False
    started = [e for e in executions if e.status != states.EXEC_PENDING]
    if not started:
        return False
    task.status = states.TASK_RUNNING
    if task.started_at is None:
        known = [e.started_at for e in started if e.started_at is not None]
        task.started_at = min(known) if known else now
    return True
```

`services/events.py::_update_task` 改为:锁 task → `list_executions` →
`converge_task(task, executions, now)` → 既有 roll-up 判定(`rollup_task_status`
+ `rerollable` + `is_valid_task_transition`,lost 重滚与 `outcome_recorded_at`
复位逻辑原样保留)。删除原"仅 `execution.status == EXEC_RUNNING`"分支——新
条件是其超集(running 事件仍然收敛,行为不变;`accepted` 事件 execution
仍为 pending,不收敛)。

`started_at` 取值:`Execution.started_at`(不用 `now`)——终态直达时
`_apply_status` 已把 execution `started_at` 设为事件时刻,task 与之对齐;
既有 running 事件路径 execution `started_at == now`,与原行为一致。

### 2. task 级对账自愈(redis/reconcile.py)

```python
ORPHAN_NO_EXECUTION = "no_execution"          # status_reason for the forced lost
REPAIR_KEY = "reconcile_repair"               # status_detail sub-key (audit)

async def repair_orphaned_tasks(session, settings, *, now) -> ReconcileReport:
    threshold = settings.agents.lost_after_stalled_seconds
    active_exec = (
        select(Execution.id)
        .where(Execution.task_id == Task.id, Execution.status.in_(tuple(states.EXEC_ACTIVE)))
        .exists()
    )
    candidates = (await session.execute(
        select(Task.id).where(Task.status.in_(tuple(states.TASK_ACTIVE)), ~active_exec)
    )).scalars().all()
    for task_id in candidates:
        # terminal-writer protocol: lock task, re-read under the lock
        task = await svc.get_task(session, task_id, for_update=True)
        if task is None or task.status not in states.TASK_ACTIVE:
            continue
        executions = await svc.list_executions(session, task_id)
        if any(e.status in states.EXEC_ACTIVE for e in executions):
            continue                      # became active meanwhile
        before = task.status
        if executions:
            svc.converge_task(task, executions, now)
            rolled = states.rollup_task_status([e.status for e in executions])
            if rolled is None or not states.is_valid_task_transition(task.status, rolled):
                continue                  # defensive; unreachable after converge
            task.status = rolled
            finished = [e.finished_at for e in executions if e.finished_at is not None]
            task.finished_at = max(finished) if finished else now
            report.orphan_rolled_up += 1
        else:
            if (now - _aware(task.created_at)) < timedelta(seconds=threshold):
                continue                  # young zero-execution row: leave it
            task.status = states.TASK_LOST
            task.status_reason = ORPHAN_NO_EXECUTION
            task.finished_at = now
            report.orphan_lost += 1
        task.status_detail = {**(task.status_detail or {}), REPAIR_KEY: {
            "from": before, "to": task.status, "reason": "no_active_execution",
            "executions": len(executions), "repaired_at": now.isoformat(),
        }}
        report.repaired_task_ids.append(task_id)
        logger.warning("task %s repaired by reconcile: %s -> %s (no active execution)", ...)
    return report
```

要点:

- **选择谓词在 SQL 侧**:`Task.status IN active AND NOT EXISTS (execution
  active)`,活动态 task 常年只有个位数到几十行(`ix_tasks_status_outcome_recorded_at`
  前缀命中),每 tick 开销可忽略;不读取 30 万行 tasks。
- **锁序与复核**:逐条 `get_task(for_update=True)`(`populate_existing`
  重读)后再 `list_executions` 复核,与事件消费者 / `mark_lost` / dispatcher
  超时 / 结果记录者共用 task → executions 锁序,并发终态写入者先提交则本
  路径看到终态直接跳过(TC-14)。
- **roll-up 语义与事件路径一致**:同一个 `rollup_task_status`(failed > lost
  > canceled > complete),`started_at` 经 `converge_task` 取 execution 最早
  开始时间,`finished_at` 取 execution 最晚结束时间——修正后的时间线反映
  真实执行,而不是修复时刻。
- **零 execution 分支**:当前创建路径在同一事务里写 task + executions(或直接
  `no_target`),零 execution 活动态只可能是遗留/异常行;沿用
  `agents.lost_after_stalled_seconds`(默认 3600s)作为观察期以免误伤任何
  未知的分步写入,超期置 `lost` + `status_reason="no_execution"`(与
  `mark_task_lost` 对零 execution 的处置一致,`no_target` 按 `states.py`
  注释仅限创建期设置,不在此复用)。
- **审计**:`status_detail["reconcile_repair"]` 记录 from/to/原因/时间;每条
  修复打一行 `warning` 日志(操作者可见)。不发消息中心通知——修复是系统
  自愈而非事故。
- **接线**:`reconcile_once` 在 execution 循环之后调用并合并计数;
  `RedisReconcileLoop._tick` 顺序不变(reconcile_once → finalize_drained_logs
  → record_task_outcomes → commit),修复后的终态 task 在**同一 tick** 被
  结果记录者处理(`outcome_recorded_at IS NULL`),两条生产任务将记为非错误
  结果。
- **幂等**:修复后 task 已终态,不再命中谓词;第二次调用报告全零。

### 3. 文档(docs/architecture/03-execution-and-logs.md)

「状态事件与对账」段:

- 收敛条件从"running 事件把 queued task 推到 running"改写为"任一 execution
  离开 pending(running 或直达终态)即收敛,再 roll-up;task 状态机不放宽";
- 新增一条:reconcile loop 每 tick 额外修复"活动态 task 但名下无活动
  execution"的孤儿行(全终态 → roll-up;零 execution 超 `lost_after_stalled_seconds`
  → `lost(no_execution)`),`status_detail.reconcile_repair` 留痕。

## 测试用例

档位说明:A = pytest / ruff 非交互命令判定,证据为命令 + 完整输出 + 退出码,
落 `evidence/`;B = 文档静态引用(`文件:行号`)。本方案 C 档为 0(无人工
交互项)。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | `test_event_consumer.py`:task queued + execution pending(`_seed`) | 直接 `apply_event(finished)`(不发 running) | execution `finished`;task `complete`;`task.started_at == execution.started_at`(非 None);`task.finished_at` 非 None;audit outcome `applied` | `evidence/tc-01-06-events.txt`:`pytest apps/server/tests/test_event_consumer.py -k <names>` 完整输出 + 退出码 |
| TC-02 | A | 同上 | 直接 `apply_event(failed, error_code="spawn_aborted")` | task `failed`,`started_at` 非 None | 同上 |
| TC-03 | A | 同上 | 直接 `apply_event(canceled)` | task `canceled`,`started_at` 非 None | 同上 |
| TC-04 | A | 同上 | 先 `apply_event(lost, lost_reason=state_missing)`,再 `apply_event(finished)` | 第一步 task `lost`;第二步 execution `reconciled_from="lost"`、task `complete`(lost 重滚不受收敛改动影响) | 同上 |
| TC-05 | A | 同上 | `running` → `finished`(既有路径) | running 后 task `running` 且 `started_at=T1`;finished 后 task `complete` 且 `started_at` 仍为 T1(未被终态覆盖);既有用例 `test_running_converges_task_and_is_idempotent` / `test_running_then_finished_rolls_up_complete` 继续通过 | 同上 |
| TC-06 | A | task queued + 两条 pending execution(扇出) | 对 e1 `finished`;再对 e2 `finished` | 第一步 task `running`(收敛但不 roll-up,e2 仍 pending);第二步 task `complete` | 同上 |
| TC-07 | A | `test_reconcile_redis.py`:task queued、`started_at=None`;1 条 execution `finished`,`started_at=finished_at=now-7d`;节点心跳新鲜 | `reconcile_once` | task `complete`;`started_at == execution.started_at`;`finished_at == execution.finished_at`;`status_detail["reconcile_repair"] == {from:"queued", to:"complete", ...}`;`report.orphan_rolled_up == 1`、`repaired_task_ids == [task.id]`;`status_reason` 保持 None | `evidence/tc-07-12-reconcile.txt`:`pytest apps/server/tests/test_reconcile_redis.py -k <names>` 完整输出 + 退出码 |
| TC-08 | A | task running;executions `[failed, finished]` 均终态 | `reconcile_once` | task `failed`(优先级 failed > complete);`finished_at` 取两者最大 | 同上 |
| TC-09 | A | task queued;executions `[finished, pending]`;节点心跳新鲜、pending 的 `created_at` 新 | `reconcile_once` | task 仍 `queued`(NOT EXISTS 谓词排除);report 修复计数为 0 | 同上 |
| TC-10 | A | 两条零 execution 的 queued task:A `created_at=now-60s`,B `created_at=now-2h`;`lost_after_stalled_seconds=3600` | `reconcile_once` | A 仍 `queued`;B `lost`、`status_reason="no_execution"`、`finished_at` 非 None;`report.orphan_lost == 1` | 同上 |
| TC-11 | A | 三条终态 task(`complete` / `lost` / `no_target`)各带零或终态 execution;另含 TC-07 场景一条 | `reconcile_once` 两次 | 三条终态 task 状态与 `status_detail` 完全不变;第一次修复 1 条,第二次 report 全零(幂等) | 同上 |
| TC-12 | A | 调度绑定的 TC-07 场景 task(`schedule_id` + `schedule_generation` 对齐当前 generation),schedule `consecutive_error_count=2` | `RedisReconcileLoop._tick()` 一次 | task `complete` 且 `outcome_recorded_at` 非 None、`outcome_erroneous is False`;schedule `consecutive_error_count == 0`(修复与结果记录同 tick) | 同上 |
| TC-13 | A | `test_reconcile_orphans_pg.py`(新,需 `DOPILOT_TEST_DATABASE_URL`,缺失则 fail 不 skip):PG 内 seed TC-07 场景 | `reconcile_once` | 与 TC-07 相同断言(验证 `NOT EXISTS` + `FOR UPDATE`/`populate_existing` 在 PG 方言下工作) | `evidence/tc-13-14-pg.txt`:`DOPILOT_TEST_DATABASE_URL=… pytest apps/server/tests/test_reconcile_orphans_pg.py` 完整输出 + 退出码 |
| TC-14 | A | PG:会话 B 先 `SELECT … FOR UPDATE` 锁住 TC-07 场景 task 行 | 会话 A 并发启动 `reconcile_once`(应阻塞);B 把 task 置 `canceled` 并 commit;等待 A 返回 | A 返回后 task 仍 `canceled`(锁下复核看到终态即跳过),`status_detail` 无 `reconcile_repair`,A 的 report 修复计数为 0 | 同上 |
| TC-15 | A | 全量 | `ruff check apps packages`;`DOPILOT_TEST_DATABASE_URL=… pytest apps/server -q` | 两者退出码 0;通过数 ≥ 基线 782 + 新增用例数 | `evidence/tc-15-ruff.txt`、`evidence/tc-15-pytest.txt` 完整输出 + 退出码 |
| TC-16 | B | 文档改动完成 | 检查 `docs/architecture/03-execution-and-logs.md` | 「状态事件与对账」含"离开 pending 即收敛"与"孤儿修复"两条,实现记录引用 `文件:行号` | 实现记录中的 `文件:行号` 引用 |

非 happy-path 覆盖:TC-02/03/04(失败/取消/丢失直达)、TC-09(部分活动不
修)、TC-10(观察期内不修)、TC-11(终态不选、幂等)、TC-14(并发终态写入者
优先)。

## 风险与回滚

- **行为变化面**:收敛条件放宽后,`failed`/`canceled` 直达也会给 task 补
  `started_at`(与 execution 侧终态兜底一致);最终状态与原来相同。收益是
  `complete` 直达不再卡死。
- **自愈误判**:谓词要求"无任何活动 execution",全终态 roll-up 是确定性的
  一致性修复,不存在合法的"全终态但 task 活动"窗口(事件路径在同一事务内
  roll-up);零 execution 分支加观察期。锁下复核保证不覆盖并发终态写入者。
- **结果记录联动**:修复后的 `complete` 任务会进入结果记录并可能**清零**
  对应调度的连续错误数(记为非错误)。对生产两条任务:两个调度当前错误数
  为 0,无实际影响。
- **性能**:每 tick 一条索引范围查询 + NOT EXISTS 相关子查询,候选集为活动
  态 task(个位数量级),无回归风险。
- **回滚**:纯代码改动、无迁移,回退镜像即可;已修复的数据是真实终态,无需
  还原。
- **上线与验证(升级后)**:`GET /api/v1/tasks?status=queued` 的 `total`
  从 2 变 0;`GET /api/v1/tasks/6044a26b…` 与 `…/d1d2c9ae…` 的 `status ==
  "complete"`、`started_at == "2026-08-25T22:22:21…"`、`status_detail.reconcile_repair.from == "queued"`;server 日志出现两行
  `repaired by reconcile`。此步在生产升级时由本会话按用户指令执行核验。
