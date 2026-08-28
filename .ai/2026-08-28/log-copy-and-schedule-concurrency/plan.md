---
status: approved
task: log-copy-and-schedule-concurrency
date: 2026-08-28
approved_at: 2026-08-28 (用户开场即预先授权:"确认并开始…你做到 push 为止";plan-review 第 19 轮 pass)
plan_review_max_rounds: 20
impl_fix_max_rounds: 20
---

# 方案:日志复制 + 定时调度并发上限

## 范围变更(用户已裁定)

**日志下载功能已于 2026-08-28 应用户要求移除**:"算了,把日志下载的功能
去掉吧,搞这么复杂"。plan 评审 round-01/03/08/09/11/15 围绕下载快照语义、
维护截断竞态、fd 生命周期、下载令牌与 HEAD 预检提出的一系列 plan-blocker,
均随该功能删除而消失,**不再纳入本方案**。

本任务现在只做两件事:

1. **日志流可复制**(仅复制,无下载);
2. **定时调度并发上限**,默认 1。

任务边界:两个功能共用一个 rawf 任务目录、一次评审、**一次提交**。
round-02 曾以"违反 AGENTS.md『一次提交一个主题』"判 plan-blocker 要求拆分,
**用户 2026-08-28 明确裁定"别拆,我明确要求放在一起"**,已记录在案,后续
轮次不应再以任务边界为由判 plan-blocker。

轮次上限:用户先要求放宽到 15 轮,后追加"改为最大 20 轮",故为 **20 轮**。

## 背景与目标

1. **日志流可复制**。`LogViewer` 目前只是一个 SSE 收流的 `<pre>`
   (`apps/web/components/features/log-viewer.tsx:96-114`),用户要把日志
   拿出去只能手工选中。
2. **定时调度并发上限**。定时触发目前只做"未下发积压"合并
   (`services/schedules.py:300-325`),注释写明"running 的任务不算,允许
   并发重复运行";`trigger_now` 则完全不合并。慢任务会自我叠加。

用户已确认的口径(2026-08-28):

| 决策点 | 结论 |
|---|---|
| 复制范围 | **当前视图缓冲**(前端,不发请求) |
| 存量 schedule 的上限 | **统一置 1**(与新建一致,承担行为变化) |
| 手动触发超限 | **提示并拒绝,不提供强制入口** |
| 定时触发超限 | **静默跳过,只记服务端日志**(不发消息中心通知、不计入 `consecutive_error_count`) |

## 改动范围

### 新增

| 文件 | 内容 |
|---|---|
| `apps/server/migrations/versions/0014_schedule_max_concurrency.py` | `schedules.max_concurrency` 列(server_default 1)+ `ix_tasks_schedule_id_status` 索引 |
| `apps/server/tests/test_schedule_concurrency.py` | 并发闸用例(SQLite) |
| `apps/server/tests/test_schedule_concurrency_pg.py` | 真实行锁 / 锁下重读 / 锁内 coalesce(PostgreSQL) |
| `apps/server/tests/test_migration_0014_pg.py` | 0013→0014→0013 真实升级与回滚(PostgreSQL) |
| `docs/decisions/0022-schedule-concurrency-limit.md` | 推翻"允许并发重复运行"的旧口径 |

### 修改

| 文件 | 内容 |
|---|---|
| `apps/server/dopilot_server/models/scheduling.py` | `Schedule.max_concurrency` 列 |
| `apps/server/dopilot_server/models/execution.py` | `Task.__table_args__` 增 `(schedule_id, status)` 索引 |
| `apps/server/dopilot_server/services/schedules.py` | 并发计数 + 行锁准入闸 + 校验 + `schedule_view` |
| `apps/server/dopilot_server/services/outbox.py` | 更新指向旧"允许并发重复运行"口径的注释 |
| `apps/server/dopilot_server/api/v1/schemas.py` | `ScheduleView` / `ScheduleCreateRequest` / `ScheduleUpdateRequest` 增字段 |
| `apps/server/tests/test_schedules.py` | 补默认值断言;**修正 `test_repeated_trigger_now_not_coalesced`**(见"存量用例冲突") |
| `apps/web/components/features/log-viewer.tsx` | 复制按钮 |
| `apps/web/lib/api/types.ts` | `Schedule.max_concurrency`、`CreateScheduleRequest.max_concurrency` |
| `apps/web/app/(app)/schedules/page.tsx` | 并发上限表单项 + 列 + 编辑预填 + 409 提示 |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | 新文案 + `errors.scheduleConcurrencyLimit` / `errors.invalidMaxConcurrency` |
| `apps/web/components/features/__tests__/log-viewer.test.tsx` | 复制用例 |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 表单/编辑/409 用例 |
| `docs/decisions/0014-node-strategy-and-push-mode.md` | 顶部标注 coalesce 口径**部分被 0022 取代** |
| `docs/decisions/README.md` | 索引新增 0022 |
| `docs/architecture/02-domain-model.md` | schedules 表补 `max_concurrency` |
| `docs/architecture/06-web-frontend.md` | 记一句日志查看器的复制能力 |

预计触及 **21 个文件 > 10**,故本 plan 在确认闸之前须过 `plan-review.sh`。

### 明确不动

- **日志下载**(已按用户要求移除):不新增下载端点、不新增下载令牌、
  不动 `logs/files.py`、不动 `logs/stream_token.py`、不动
  `auth/dependencies.py`、不动 `api/v1/tasks.py`;
- SSE 推流协议、日志落盘格式、日志洪泛防护(0021)的逻辑;
- `has_undispatched_backlog_for_schedule` 的积压合并**行为**(只改注释,
  并把调用点移进锁内);
- 自动禁用 / `consecutive_error_count` / `outcome_generation` 语义;
- 模板直跑与直接产物运行路径。

## 实现方案

### A. 日志复制

`log-viewer.tsx` 头部加一个复制按钮(`data-testid="log-copy"`):

- 写**当前视图缓冲**(组件里那份 `content` state),不发任何请求;
- 调用前先判可用性:`navigator.clipboard?.writeText` 不存在(HTTP 非安全
  上下文)→ `toast.error(t("logs.copyUnavailable"))`;存在则
  `await writeText`,成功 `toast.success(t("logs.copied"))`,`reject`
  (权限被拒)→ `toast.error(t("logs.copyFailed"))`。整段包在 `try/catch`
  里,不产生未处理的 Promise 拒绝,组件不崩溃;
- 缓冲为空时按钮 `disabled`;
- **范围要说清且可断言**:按钮带一段无障碍可读的说明
  (`logs.copyHint`,文案表达"复制**当前视图**内容")。SSE 首屏只回放尾部
  (`first_screen_max_lines` / `first_screen_max_bytes`,默认 1MiB),复制到
  的不是全量日志,不能让用户误解;
- `sonner` 的 `<Toaster>` 已挂在 `components/providers.tsx:41`,但全仓库
  尚无 `toast()` 调用点,本任务是第一处。

### B. 定时调度并发上限

**B1. 数据模型**

- `Schedule.max_concurrency: int`,`nullable=False`,模型默认 `1`,迁移
  `server_default="1"`(存量行随之回填为 1);
- 语义:`>= 1` 为上限;`0` 为**不限**(逃生舱);负数拒绝;
- **值域上界必须与列类型对齐**(round-15 R-02):列是 SQLAlchemy
  `Integer`,PostgreSQL 上是有符号 32 位,`2147483648` 会通过 Pydantic 与
  朴素的 `>= 0` 校验,却在提交时炸成 DataError/500。故合法区间明确定为
  **`0 .. 2147483647`**,越界由 service 返回结构化 400,前端输入框同步
  设 `max`;
- `Task` 增 `Index("ix_tasks_schedule_id_status", "schedule_id", "status")`
  —— 目前 `tasks.schedule_id` **无任何索引**(`models/execution.py:86`),
  并发计数会变成全表扫描。

**B2. 并发口径**

计数 = 该 schedule 名下处于 `TASK_ACTIVE` 的 **task 行数**。`TASK_ACTIVE`
是 `frozenset({queued, running, finalizing})`(`services/states.py:45`),
实现**直接引用该常量**,不得手写子集。

- 一个 task 扇出多个 execution,**按 task 计 1**;
- 终止态(含 `no_target`)不计入,额度自动释放;
- 模板直跑 / 直接产物运行的 task `schedule_id` 为 NULL,天然不计入;
- 不区分 `source`:`schedule_timer` 与 `schedule_trigger_now` 共用**同一个**
  额度池 —— 这正是"手动触发也纳入并发指标"的要求。计数查询**只按
  `schedule_id` + 状态过滤,不得带 `source` 条件**;TC-29 从两个方向
  (定时任务挡住手动触发、手动任务挡住定时触发)验证,排除"分池"实现;
- 不按 `outcome_generation` 过滤:并发是"此刻占用"。

**B3. 准入闸与行锁**(`services/schedules.py`)

```python
SKIP_MISSING = "missing"; SKIP_DISABLED = "disabled"
SKIP_BACKLOG = "backlog"; SKIP_CONCURRENCY = "concurrency"

@dataclass(frozen=True)
class FiringSlot:
    granted: bool
    schedule: Schedule | None = None
    skip_reason: str | None = None      # SKIP_* 之一
    active: int | None = None           # 仅 SKIP_CONCURRENCY 时有值
    limit: int | None = None            # 同上

async def count_active_tasks_for_schedule(session, schedule_id) -> int
async def acquire_firing_slot(
    session, schedule_id: str, *,
    raise_on_full: bool, require_enabled: bool, coalesce_backlog: bool,
) -> FiringSlot
```

它是一次 schedule 触发的**唯一准入闸**,把"是否存在 / 是否启用 / 是否有
未下发积压 / 是否超并发"四道判断收进**同一个串行区**。返回结构化结果而
不是裸 `None`,否则调用方分不清跳过原因,超限日志会把"禁用"和"正常
coalesce"误报成超限。

顺序(**全部在锁内**):

1. `SELECT ... WHERE id = :id FOR UPDATE`,带
   `.execution_options(populate_existing=True)` —— 与仓库既有锁查询同一
   写法(`services/executions.py:276-280`),用锁下的行覆盖 identity map
   里的陈旧副本。**绝不用锁前的值做任何判断**(包括 `0` 的快速放行):
   否则并发把上限从 0 改成 1 并提交后,旧请求仍会无锁建单,穿透新上限;
2. 行不存在 → `raise_on_full` 为真时抛 404 `schedule.not_found`,否则
   `skip_reason=SKIP_MISSING`;
3. `require_enabled` 且锁下 `enabled` 为假 → `SKIP_DISABLED`(锁内复核
   取代 `fire_timer` 现在那句锁外的 defensive 判断);
4. `coalesce_backlog` 且 `has_undispatched_backlog_for_schedule()` 为真 →
   `SKIP_BACKLOG`。**这一步必须在锁内**:该查询只看得见已提交的行,若放
   在取锁之前,存在这条竞态——trigger-now 已持锁正在建单,timer 先查到
   "无积压",随后阻塞在行锁上;等 trigger-now 提交了带未决 outbox 的任务
   并放锁,timer 拿到锁却不再复查,于是继续建单,破坏既有 coalesce 语义;
5. 用**锁下的** `max_concurrency` 判断:`== 0` → 放行;
6. 否则计数 active task,`active >= limit` → `raise_on_full` 为真则抛
   `ApiError(409, "schedule.concurrency_limit",
   "errors.scheduleConcurrencyLimit", {"active": n, "limit": m})`,否则
   `FiringSlot(skip_reason=SKIP_CONCURRENCY, active=n, limit=m)`;
7. 放行返回 `FiringSlot(granted=True, schedule=<锁下实例>)`,调用方后续
   一律用该实例(`overrides` / `outcome_generation` 同取锁下权威值)。

**锁的生命周期**:持有到执行器那次"task + executions + outbox +
log_files"的原子提交为止(`executors/scrapyd.py:105-106`)。该提交在
**XADD 之前**(`scrapyd.py:108-114` 先 commit 再 `try_dispatch`),因此
**行锁绝不跨 Redis 网络调用**,持锁窗口就是一次本地建单事务。

**与既有锁序的关系**:既有锁序是
`task → executions → execution_log_files → schedule`
(`services/executions.py:275`)。本闸**只取 schedule 单行锁**,持锁期间
**不申请任何 task/execution 行锁**(计数是无锁 `SELECT COUNT`,建单是
`INSERT`),故**不构成环**;最坏情况只是终态写入者在其锁序末端等待本闸
释放,而本闸从不反向等待 task 锁。

SQLite 会忽略 `FOR UPDATE`(编译为空),真实串行性由 PG 用例覆盖
(TC-12 / TC-13 / TC-14)。

**接入点**:

- `trigger_now`:第一步调 `acquire_firing_slot(raise_on_full=True,
  require_enabled=False, coalesce_backlog=False)` —— 对禁用调度依然可用,
  且**永不 coalesce**(保持既有用户决策);超限抛 409,**不创建任务**;
- `fire_timer`:调 `acquire_firing_slot(raise_on_full=False,
  require_enabled=True, coalesce_backlog=True)`,原先写在函数体里的
  `enabled` 判断与积压合并**都移入锁内**(行为不变,变得可串行化)。
  跳过时 **仅当 `skip_reason == SKIP_CONCURRENCY`** 才以模块级
  `logger.info` 记 `schedule %s timer firing skipped: concurrency %d/%d`;
  另两种跳过**不得**打这行日志。随后 `return None`。**不**写 notification、
  **不**动 `consecutive_error_count`(用户确认:静默跳过)。

**B4. 输入校验契约**

沿用仓库既有的 `interval_seconds` 双层形态
(`services/schedules.py:55-62`),不发明新机制:

| 输入 | 处理层 | 结果 |
|---|---|---|
| 合法 int,`0 .. 2147483647` | — | 正常写入 |
| **值域**非法(负数、`> 2147483647`) | service `_validate_max_concurrency` | **400** `schedule.invalid_max_concurrency` / `errors.invalidMaxConcurrency` |
| **类型**非法(`"abc"`、`1.5`) | Pydantic / FastAPI | **422**(既有校验响应形态,不改全局异常处理) |
| **布尔值**(`true` / `false`) | schema 的 before-validator | **422** —— 必须显式拒绝 |

**布尔值必须显式拒绝**。已实测 Pydantic v2 普通 `int` 字段的行为:
`True → 1`、`False → 0`、`'3' → 3`、`3.0 → 3`、`1.5` 与 `'abc'` 报错。
即 `false` 会被静默收敛成 `0`,而 `0` 正是"**不限并发**"——一个写错类型的
请求会悄悄把并发闸整个关掉;且 `isinstance(True, int)` 为真,service 侧的
`isinstance` 也拦不住。故两层都排除 bool:schema 加
`field_validator(mode="before")`,`isinstance(v, bool)` → `ValueError` →
422;service `_validate_max_concurrency` 同样先判 bool → 400(覆盖绕过
API 直调 service 的路径)。

- `ScheduleCreateRequest.max_concurrency: int = 1`(**不**加 `ge=0`——值域
  校验统一由 service 承担,保证 API 与直调 service 得到同一个 400 契约);
- `ScheduleUpdateRequest.max_concurrency: int | None = None`(PUT 走
  `exclude_unset`,不传即不改);
- `ScheduleView.max_concurrency: int = 1`;
- `create_schedule` 与 `update_schedule` **两条路径都要校验**。

**B5. 前端**

- 新建/编辑对话框:数字输入 `max_concurrency`,默认 1,`min=0`、
  `max=2147483647`,说明"0 表示不限";**编辑时预填该调度的当前值**;
- **`0` 必须能真正从 UI 走通**:它是 ADR 与风险处置依赖的逃生舱,而唯一
  管理入口就是这个界面。实现**禁止**用 `Number(v) || 1`、`v || 1` 这类会
  把 `0` 吞成 `1` 的写法(用 `Number.isInteger` + 显式判空),输入框下限
  不得设成 1;
- 列表加一列展示上限,`0` 渲染为本地化的"不限"(`schedules.unlimited`);
- `onTrigger` 目前**没有 try/catch**(`schedules/page.tsx:329-339`),409
  会变成未处理的 Promise 拒绝。改为捕获:命中 `schedule.concurrency_limit`
  时弹 `toast.error(t("schedules.concurrencyLimitHit", {active, limit}))`
  且**不跳转**;其他错误弹通用失败提示。

### C. 决策与文档回写

- 新增 `docs/decisions/0022-schedule-concurrency-limit.md`(四段式):
  推翻"允许并发重复运行"的理由、新口径、`0` 逃生舱、存量回填为 1 的影响
  与回滚办法;
- `docs/decisions/0014-*.md` 的"影响"节第 2 条记着旧 coalesce 口径
  (`0014:17-18`),按 `docs/decisions/README.md:14-15` 的规则在其**顶部
  标注"coalesce 口径已被 0022 部分取代"**(节点策略部分仍有效);
- `docs/decisions/README.md` 索引新增 0022;
- `services/outbox.py:215-222` 的"允许并发重复运行(user decision #2)"
  注释同步更新,避免与新 ADR 打架;
- `docs/architecture/02-domain-model.md` 补 `max_concurrency` 字段;
- `docs/architecture/06-web-frontend.md` 记一句日志查看器的复制能力。

### 存量用例冲突

`apps/server/tests/test_schedules.py:258` 的
`test_repeated_trigger_now_not_coalesced` 用**不指定上限**的 schedule 连续
trigger-now 两次并断言两次都成功。默认上限变成 1 后,第二次必然 409,该
用例**必挂**——不修正它,全量回归拿不到绿。

处置:把该用例的 schedule 显式建成 `max_concurrency=0`(不限),其余断言
不变。它的立意是"trigger-now 不做 backlog coalesce",与并发上限无关;
默认上限 1 的行为由新用例覆盖,职责不重叠。

已逐条核对其余触发相关的存量用例,**不受影响**:`test_schedules.py` 其他
trigger-now 用例(:154、:186、:237、:251、:407、:588)均为新建 schedule +
**仅触发一次**;`test_fire_timer_dispatches_when_no_backlog`(:278)0 个
active;`test_fire_timer_coalesced_when_undispatched_backlog`(:304)与
`test_fire_timer_noop_when_disabled`(:414)期望的就是跳过,新闸分别走
`SKIP_BACKLOG` / `SKIP_DISABLED`,结果不变;`test_python_wheel.py:310`、
`test_templates.py:231` 为单次触发;`test_outcomes.py:185` 用 `_task()`
直接造行,不经过闸门;`test_scheduler_runner.py` 只测 trigger 构造。

### 实现顺序

1. 模型 + 迁移 + 索引;
2. 准入闸(service)+ schema + 校验,配套 pytest;
3. 前端 LogViewer 复制按钮;
4. 前端 schedules 页 + 文案;
5. vitest 用例;
6. docs 回写 + ADR;
7. 全量 lint / tsc / pytest / vitest 取证。

## 测试用例

C 档 0 条(剪贴板在 jsdom 中可由 vitest mock 判定,按"可自动化者一律
A 档"落 A)。

**证据落点**(A 档统一契约:每条留**执行命令 + 完整 stdout/stderr +
退出码**):`evidence/backend-tests.log`(SQLite)、
`evidence/pg-tests.log`(PostgreSQL)、`evidence/web-tests.log`(vitest)、
`evidence/lint-typecheck.log`。

**PostgreSQL 前置**:`conftest.py:552-569` 规定缺 `DOPILOT_TEST_DATABASE_URL`
时 PG 用例 **fail 而非 skip**,故凡会收集到 PG 用例的命令(TC-12~15、
TC-25)一律带该变量前缀:
`DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot`
(对应已在运行的 `docker-db-1`)。

**并发用例的共同前置**:两个执行器在**没有健康且能力匹配的节点**时,会把
新 task 直接提交为终态 `no_target`(`executors/scrapyd.py:63-74`),它**不占
并发额度**。因此凡要"真实建单并占额度"的用例(TC-04~09、TC-12~14),前置
一律先造健康节点,并在放行后**断言新任务处于 active(非 `no_target`)**,
否则用例会假绿。⚠️ **PG 用例不能用 `seeder` fixture**——它固定绑定
`db_session`(SQLite,`conftest.py:410`),节点会写进另一个库;PG 用例须在
`pg_sessionmaker()` 的 session 内自行构造 `Seeder(pg_session, settings)`,
并保证节点/产物/模板/schedule/触发事务**全部同库**。

⚠️ **迁移用例(TC-15)的数据库生命周期**:既有 PG fixture 用
`Base.metadata.drop_all/create_all` 建表,**不管 `alembic_version`**;而迁移
用例必须从 revision 0013 起步。两者共用同一个库,顺序一旦交错就会留下不一致
基线。故 TC-15 自带 `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` 的
硬重置(连 `alembic_version` 一起清)+ `alembic upgrade 0013` 建基线,并在
`finally` 中重置回 `create_all` 形态,使其**与执行顺序无关、可重复**。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 已建模板 | `POST /schedules` 不传 `max_concurrency`;再传 `3`;再传 `0`;再传 `2147483647` | 依次得到 `1` / `3` / `0` / `2147483647` | 命令 `.venv/bin/python -m pytest apps/server/tests/test_schedule_concurrency.py -v` + 完整 stdout/stderr + 退出码 → `evidence/backend-tests.log`,锚点 `test_max_concurrency_defaults_and_values` |
| TC-02 | A | 已建模板 | `POST /schedules` 依次传 `-1` / `2147483648` / `"abc"` / `1.5` / `true` / `false`;并直接调 `sched_svc.create_schedule(..., max_concurrency=True)` 与 `=2147483648` | `-1` 与 `2147483648` → **400** `schedule.invalid_max_concurrency`(上界与 32 位 Integer 对齐,不留到提交时炸成 500);`"abc"`、`1.5`、`true`、`false` → **422**(bool 被 before-validator 拒绝,不被收敛成 1/0);service 直调 `True` / `2147483648` → **400**(**异常路径**) | 同 TC-01 命令与证据文件,锚点 `test_max_concurrency_invalid_inputs` |
| TC-03 | A | 已有 `max_concurrency=1` 的 schedule | `PUT /schedules/{id}` 依次传 `5` / `-1` / `2147483648` / `true` / `false`;并直接调 `sched_svc.update_schedule(..., max_concurrency=True)` | `5` → 200 且视图返回 5;`-1` 与 `2147483648` → **400**;**`true` 与 `false` → 422**(更新路径的 before-validator 同样拒绝 bool —— 只给 Create schema 加 validator 的实现会在此暴露:PUT `false` 会被收敛成 `0`,悄悄把并发闸关掉);service 直调 `update_schedule` 传 `True` → **400**(**异常路径**;round-16 R-01) | 同 TC-01 命令与证据文件,锚点 `test_update_max_concurrency` |
| TC-04 | A | 已造健康节点;schedule `max_concurrency=2`,名下 0 个 active | 连续 `trigger-now` 三次 | 前两次 200 且各建一个**active**(非 `no_target`)任务,**第三次 409**,`detail` 含 `active=2`/`limit=2`(证明不是把任意非零上限当 1)(**边界路径**) | 同 TC-01 命令与证据文件,锚点 `test_limit_two_allows_two_then_rejects` |
| TC-05 | A | 已造健康节点;schedule `max_concurrency=1`;参数化把名下唯一 task 置为 `queued` / `running` / `finalizing` | 每种状态下 `trigger-now` | 三种状态**均** 409(三个 active 态等价计数)(**边界路径**) | 同 TC-01 命令与证据文件,锚点 `test_all_active_statuses_count` |
| TC-06 | A | 已造健康节点;schedule `max_concurrency=1`,名下唯一 task 参数化置为 `complete` / `failed` / `canceled` / `lost` / `no_target` | 每种状态下 `trigger-now` | 均 200 且新建任务为 active(终止态释放额度) | 同 TC-01 命令与证据文件,锚点 `test_terminal_statuses_release_slot` |
| TC-07 | A | 已造健康节点;schedule `max_concurrency=0`,名下**已有 2 个 active** task | 连续 `trigger-now` 两次 | 均 200 且各建一个 active 任务(`0` 是真正的"不限",不是零并发也不是普通有限值)(**行为验证**) | 同 TC-01 命令与证据文件,锚点 `test_zero_means_unlimited` |
| TC-08 | A | 已造健康节点;schedule A `max_concurrency=1` 名下 0 个 active;schedule B 名下 1 个 active;另有 1 个 `source=template`、`schedule_id=NULL` 的 active task | 对 A `trigger-now` | 200 成功(其他 schedule 与模板直跑不计入 A 的并发) | 同 TC-01 命令与证据文件,锚点 `test_count_scoped_to_own_schedule` |
| TC-09 | A | 已造健康节点;schedule `max_concurrency=2`;名下有 **1 个 active task,但该 task 扇出了 2 个 execution** | `trigger-now` | 200 成功(active 计为 **1** 而非 2;若误 join execution 表会错误 409)(**口径边界**) | 同 TC-01 命令与证据文件,锚点 `test_multi_execution_task_counts_once` |
| TC-10 | A | schedule **`enabled=true`**、`max_concurrency=1`,名下已有 1 个 `running` task;`caplog` 捕获 INFO | 直接调 `sched_svc.fire_timer` | 返回 `None`;未创建新任务;`consecutive_error_count` 保持 0;`notifications` 表无新行;`caplog` 中出现约定的跳过日志(含 schedule id 与 `1/1`)(**异常路径**) | 同 TC-01 命令与证据文件,锚点 `test_fire_timer_silently_skipped_when_full` |
| TC-11 | A | 参数化:① `enabled=false`;② `enabled=true` 且存在未下发积压;两者额度均有余量;`caplog` 捕获 INFO | 每种场景:(a) 直接调 `acquire_firing_slot(require_enabled=True, coalesce_backlog=True)`;(b) 再调 `fire_timer` | (a) `granted is False`,`skip_reason` 分别为 `SKIP_DISABLED` / `SKIP_BACKLOG`,`active`/`limit` 均为 `None`;(b) 返回 `None` 且不建任务;`caplog` 中**不出现**并发超限那行日志(禁用与正常 coalesce 不得被误报为超限)(**异常路径**) | 同 TC-01 命令与证据文件,锚点 `test_non_concurrency_skips_do_not_log_limit` |
| TC-12 | A | **PostgreSQL**;在 PG session 内用 `Seeder(pg_session, settings)` 造健康节点(**不得**用绑 SQLite 的 `seeder` fixture),全部前置同库;schedule `max_concurrency=1`,名下 0 个 active | `asyncio.gather` 并发发起两次 `trigger_now`(各自独立 session) | 恰好 1 次成功、1 次抛 409;成功那个任务处于 **active**;最终 active task 恰为 1(真实行锁下不穿闸)(**异常路径 / 竞态**) | 命令 `DOPILOT_TEST_DATABASE_URL=… .venv/bin/python -m pytest apps/server/tests/test_schedule_concurrency_pg.py -v` + 完整 stdout/stderr + 退出码 → `evidence/pg-tests.log`,锚点 `test_concurrent_trigger_now_row_lock` |
| TC-13 | A | **PostgreSQL**;前置同 TC-12;schedule 初始 `max_concurrency=0`(不限),名下**已有 1 个 active** task | ① session A 先把该 `Schedule` 读进 identity map(模拟锁前读到旧值 0);② session B 把 `max_concurrency` 改为 `1` 并**提交**;③ A 用手上那个陈旧实例继续 `trigger_now` | A 必须 **409**(用的是锁下新值 `1` 而非锁前的 `0`);未创建新任务。若实现用锁前的值,此处会错误放行(**异常路径 / 线性化**) | 同 TC-12 命令与证据文件,锚点 `test_limit_change_visible_under_lock` |
| TC-14 | A | **PostgreSQL**;前置同 TC-12;schedule **`enabled=true`**(默认 false,不置真会因 `SKIP_DISABLED` 提前返回而误通过)、`max_concurrency=0`(排除并发上限干扰),名下 0 个 active;事务 A **手工构造**(不走 `trigger_now`、不经 dispatcher),沿用既有 PG 交错写法(`test_log_locking_pg.py:73-96`) | ① A:自有 session 调 `acquire_firing_slot` 取得行锁 → `create_task` + `create_run_outbox`(未下发)→ `entered.set()` → `await release.wait()` → `commit()`;② 等 `entered` 后 `asyncio.create_task` 跑 B —— B **直接调 `acquire_firing_slot(require_enabled=True, coalesce_backlog=True)`** 取其 `FiringSlot`(不调 `fire_timer`,后者跳过时只返回 `None`)→ `await asyncio.sleep(0.3)` → 断言 B **尚未完成**(阻塞在 `FOR UPDATE`);③ `release.set()`;④ await B;⑤ A 提交后用独立 session 调一次 `fire_timer` | ④ B 的 `granted is False` 且 **`skip_reason == SKIP_BACKLOG`**(不是 `SKIP_DISABLED`);⑤ `fire_timer` 返回 `None` 且不建第二个任务,最终任务总数为 1。若 coalesce 查询留在锁外,B 会在 t0 查到"无积压"、拿锁后判定放行,④ 即失败。A 全程不调 XADD,其 outbox 始终未下发,不存在"被提前标记 sent 导致偶发绿灯"(**异常路径 / 竞态**) | 同 TC-12 命令与证据文件,锚点 `test_timer_coalesce_sees_backlog_committed_under_lock` |
| TC-15 | A | **PostgreSQL**;该用例**自带隔离与可重复的基线**(round-18 R-01):它与其他 PG 用例共用同一个库,而那些用例走 `Base.metadata.drop_all/create_all` 且**不清理 `alembic_version`**,会留下"版本标记为 0013 但业务表已被删"之类的不一致状态,导致本用例在 `ALTER TABLE schedules` 处失败。故本用例在自己的 fixture 里先做硬重置:`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`(同时清掉业务表与 `alembic_version`)→ `alembic upgrade 0013` 建立干净基线 → 插入一条存量 schedule(不带 `max_concurrency`)与一条带 `schedule_id` 的存量 task。**`finally` 中再次硬重置并 `create_all`**,把库还原成后续用例期望的形态,保证与执行顺序无关、可重复运行 | ① `alembic upgrade 0014`(经 `DOPILOT_DATABASE_URL` 指向 PG 测试库,程序化调用 `alembic.command`);② 查存量行与索引;③ `alembic downgrade 0013` | ① 升级成功(revision 链正确、可执行);② 存量 schedule 的 `max_concurrency` **== 1**(`server_default` 真实回填,不是只在 ORM 层有默认值),且 `ix_tasks_schedule_id_status` 存在于 `pg_indexes`;③ 回滚成功,列与索引被移除。单独运行与随 TC-25 全量运行**结果一致**(**升级数据路径 / 可重复性**) | 命令 `DOPILOT_TEST_DATABASE_URL=… .venv/bin/python -m pytest apps/server/tests/test_migration_0014_pg.py -v` + 完整 stdout/stderr + 退出码 → `evidence/pg-tests.log`,锚点 `test_migration_0014_backfills_and_indexes`;另在 TC-25 的全量输出中确认同一用例通过 |
| TC-16 | A | LogViewer 已收到 SSE 内容 | 点击复制按钮(mock `navigator.clipboard.writeText`) | `writeText` 收到与视图缓冲一致的字符串;弹成功 toast | 命令 `corepack pnpm --filter web test -- log-viewer` + 完整 stdout/stderr + 退出码 → `evidence/web-tests.log`,锚点 `copies the current buffer` |
| TC-17 | A | LogViewer 未收到任何内容 | 渲染后检查按钮 | 复制按钮 `disabled`(**边界路径**) | 同 TC-16 命令与证据文件,锚点 `disables copy when the buffer is empty` |
| TC-18 | A | LogViewer **已收到 SSE 内容**(缓冲非空,复制按钮处于启用态——否则按钮 disabled,根本进不到异常分支);`navigator.clipboard` **不存在**(非安全上下文;测试中删除该属性) | 点击复制按钮 | 弹 error toast;不抛未捕获异常;组件仍可渲染(**异常路径**;round-16 R-02) | 同 TC-16 命令与证据文件,锚点 `warns when clipboard is unavailable` |
| TC-19 | A | LogViewer **已收到 SSE 内容**(缓冲非空,按钮启用);`navigator.clipboard.writeText` mock 为 `reject`(权限被拒) | 点击复制按钮 | 弹 error toast;无未处理 Promise 拒绝;组件不崩溃(**异常路径**;round-16 R-02) | 同 TC-16 命令与证据文件,锚点 `warns when clipboard write is rejected` |
| TC-20 | A | LogViewer 正常渲染 | 用可访问查询读取复制按钮的说明 | 说明存在且表达"**当前视图**"范围(文案来自 i18n `logs.copyHint`;整段遗漏说明则失败) | 同 TC-16 命令与证据文件,锚点 `explains the copy scope` |
| TC-21 | A | schedules 页面打开**新建**对话框 | 填名称/模板/并发上限 2 并提交 | `createSchedule` 收到的 payload 含 `max_concurrency: 2` | 命令 `corepack pnpm --filter web test -- schedules` + 完整 stdout/stderr + 退出码 → `evidence/web-tests.log`,锚点 `submits max_concurrency on create` |
| TC-22 | A | 列表里存在 `max_concurrency=4` 的调度 | 打开该行**编辑**对话框 → 改成 3 → 提交 | 对话框打开时输入框**预填 4**(不是默认 1);提交后 `updateSchedule` 收到 `max_concurrency: 3`;列表列展示该值 | 同 TC-21 命令与证据文件,锚点 `prefills and updates max_concurrency on edit` |
| TC-23 | A | 列表中存在一个 `max_concurrency=0` 的调度 | ① 新建对话框填 `0` 并提交;② 打开那个 `0` 调度的编辑框;③ 检查列表该行展示 | ① `createSchedule` 收到 `max_concurrency: 0`(**不是 1**,防 `Number(v) 或 1` 这类写法吞掉 0);② 编辑框预填 `0`;③ 列表渲染本地化的"不限"而非裸 `0`(**逃生舱可用性**) | 同 TC-21 命令与证据文件,锚点 `supports zero as unlimited` |
| TC-24 | A | mock `triggerSchedule` 抛 409 `schedule.concurrency_limit` | 点击"立即触发" | 弹 error toast;`router.push` **未**被调用(不跳转)(**异常路径**) | 同 TC-21 命令与证据文件,锚点 `shows a toast when the concurrency limit is hit` |
| TC-25 | A | 全量后端用例(含 PG 用例) | `DOPILOT_TEST_DATABASE_URL=… .venv/bin/python -m pytest apps/server apps/agent packages` | 退出码 0,无回归(变量已带,PG 用例不会因缺环境而 fail) | 该完整命令行 + 完整 stdout/stderr + 退出码 → `evidence/backend-tests.log` |
| TC-26 | A | 工作区全量改动 | `ruff check apps packages`;`corepack pnpm --filter web lint`;`corepack pnpm --filter web typecheck` | 三者退出码均为 0 | 三条命令 + 各自完整 stdout/stderr + 退出码 → `evidence/lint-typecheck.log` |
| TC-29 | A | 已造健康节点;schedule **`enabled=true`**、`max_concurrency=1`。两个方向各跑一次:① 名下已有 1 个 **`source=schedule_timer`** 的 active task;② 名下已有 1 个 **`source=schedule_trigger_now`** 的 active task | ① 调 `trigger-now`;② 调 `sched_svc.fire_timer` | ① **409**(定时产生的任务占住了手动触发的额度);② 返回 `None` 且**不创建任务**(手动产生的任务占住了定时的额度)。两个方向都必须命中——把 timer 与 trigger-now 拆成两个独立额度池的实现会在此暴露,而这正是"手动触发也纳入并发指标"这条需求的核心验收(**跨来源共用额度**;round-17 R-01) | 同 TC-01 命令与证据文件,锚点 `test_quota_shared_across_sources` |
| TC-27 | B | 迁移与索引已写(真实升级行为另由 **TC-15** 验证) | 检查 `0014_schedule_max_concurrency.py` 与 `models/execution.py` | 迁移 `upgrade` 含 `add_column("schedules", "max_concurrency", server_default="1")` 与 `create_index("ix_tasks_schedule_id_status", ...)`,`downgrade` 对称回滚;模型侧存在同名 `Index` | 代码引用(`文件:行号`) |
| TC-28 | B | docs 已回写 | 检查 `docs/decisions/0022-*.md`、`0014-*.md` 顶部标注、`decisions/README.md` 索引、architecture 两篇、`outbox.py` 注释 | 0022 存在且写明推翻旧口径 / `0`=不限 / 存量回填为 1;0014 顶部有"coalesce 口径已被 0022 部分取代";README 索引含 0022;architecture 已补字段与复制能力;`outbox.py` 旧注释已同步 | 代码/文档引用(`文件:行号`) |

合计 29 条:A 档 27,B 档 2,C 档 0(满足 ≤ 1/3)。异常/边界路径 15 条
(TC-02、03、04、05、10、11、12、13、14、17、18、19、23、24、29)。

## 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| **存量 schedule 统一置 1 改变现网行为** | 现网若有依赖重叠运行的调度,升级后会被静默跳过(定时)或拒绝(手动) | 用户已确认此口径。ADR 与升级说明写明;逃生舱是把该 schedule 的 `max_concurrency` 改成 `0`(不限)或更大值,无需回滚版本 |
| **timer 与 trigger-now 被实现成两个独立额度池** | 手动触发实际没纳入并发指标,与用户需求相悖 | 计数查询不带 `source` 条件;TC-29 双向验证 |
| **任务卡在 active 永久占额度** | agent 失联导致 task 长期 `running`,后续触发一直被挡 | 已有心跳与手动 `mark-lost` 兜底;409 的 detail 返回 `active` 计数,前端提示引导用户去任务页处理。ADR 记录为已知取舍 |
| **上限在等锁期间被并发改掉** | 用锁前的旧值判断会穿透新上限 | B3"先锁后读 + `populate_existing=True`",一切判断(含 `0`)都基于锁下权威行;TC-13 在 PG 上验证线性化 |
| **定时 coalesce 与行锁的先后** | 积压查询若在锁外,会漏看先行事务刚提交的未决 outbox,导致重复建单 | 四道判断收进锁内同一串行区;TC-14 以 `max_concurrency=0` 排除干扰、A 事务全程不下发后验证 |
| **布尔值被 Pydantic 收敛成 0/1** | `false` 静默变成"不限",把并发闸整个关掉 | schema before-validator(Create 与 Update **两个** schema 都要加)与 service 双层显式拒绝 bool;TC-02 覆盖 POST 与 create 直调,TC-03 覆盖 PUT 与 update 直调 |
| **值域超出 32 位 Integer** | `2147483648` 通过校验后在提交时炸成 500 | 合法区间定为 `0..2147483647`,service 返回结构化 400,前端 `max` 同步;TC-02 / TC-03 覆盖 |
| **跳过原因被混为一谈** | 禁用/积压被误记成"并发超限",排障误导 | 准入闸返回结构化 `FiringSlot`,超限日志只在该分支打;TC-11 断言另两种跳过不产生该日志 |
| **`0=不限` 在 UI 上走不通** | 逃生舱形同虚设(唯一管理入口是 Web) | B5 禁止把 `0` 吞成 `1` 的写法、下限为 0;TC-23 覆盖提交 0 / 预填 0 / 列表显示"不限" |
| **无健康节点导致并发用例假绿** | 新任务直接终态 `no_target`,不占额度,上限永远测不出来 | 并发用例统一前置造健康节点并断言任务为 active;**PG 用例在 PG session 内自建 `Seeder`** |
| **默认上限 1 打挂存量用例** | `test_repeated_trigger_now_not_coalesced` 必挂 | 已定位为唯一冲突项并给出处置,其余用例逐条核对不受影响 |
| **迁移在真实库上跑不通 / 存量未回填** | 只看迁移源码无法发现 revision 链错误或 `server_default` 未生效 | TC-15 在 PG 上真实执行 0013→0014→0013 |
| **迁移用例与其他 PG 用例抢同一个库** | 其他用例的 `drop_all` 不清 `alembic_version`,交错执行会让迁移用例踩到不一致基线而失败 | TC-15 自带 `DROP SCHEMA public CASCADE` 硬重置 + `upgrade 0013` 建基线,`finally` 还原;单跑与全量跑结果一致 |
| **剪贴板在非安全上下文不可用** | HTTP 部署下 `navigator.clipboard` 为 undefined | 调用前判存在性,不可用/被拒均弹 error toast(TC-18、TC-19);不做已废弃的 `document.execCommand` 回退 |
| **首次引入 `toast()` 调用** | sonner 已挂载但零调用点 | vitest 用例直接断言 toast 行为;`Toaster` 挂载点已在 `providers.tsx:41` |

**回滚**:两个功能均为纯增量。数据库层 `alembic downgrade 0013` 撤销列与
索引;代码层单次提交,`git revert` 一步回退。日志查看器只加了一个按钮,
不触碰 SSE 与既有日志接口。
