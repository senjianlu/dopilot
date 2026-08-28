---
status: approved
task: schedule-tasks-link-and-target-search
date: 2026-08-28
approved_at: 2026-08-28 21:40
plan_review_max_rounds: 10
impl_fix_max_rounds: 10
---

# 方案:调度→任务记录快速查看 + 任务页目标名模糊搜索

## 背景与目标

两个独立但共用同一条后端查询路径的小功能,合并为一个任务:

1. **调度 → 任务记录快速查看**:`schedules` 页每行加一个入口,点开直接
   看到"这个调度产生过哪些任务"。目前没有任何路径能按调度过滤任务——
   `Task.schedule_id` 列存在(`models/execution.py:86`)且已被上一任务加的
   `ix_tasks_schedule_id_status`(`models/execution.py:136`)索引覆盖,但
   `list_tasks_page()` 与 `GET /api/v1/tasks` 都没有暴露该过滤维度。
2. **任务页按目标名模糊搜索**:`tasks` 页现有筛选只有 status 与
   build_artifact 两个下拉(`app/(app)/tasks/page.tsx:206-247`),目标名
   (`Task.target`,形如 `demo:alpha`)只能靠肉眼翻页找。加一个搜索框,
   对 `target` 做大小写不敏感的子串匹配。

用户已敲定的三点(2026-08-28 对话):

- 模糊搜索**只匹配 `target`**,不扩展到 build artifact 名或 task id;
- 调度入口形态为**跳转 tasks 页并带筛选参数**,不做页内抽屉/弹窗;
- plan 评审与实现修复轮次上限**各 10 轮**(已写入本文件 frontmatter)。

不需要数据库迁移:两个功能都只是给既有列加查询条件。

## 改动范围

### 后端(3 个文件)

| 文件 | 改动 |
|---|---|
| `apps/server/dopilot_server/services/executions.py` | `list_tasks_page()` 增加 `schedule_id` 与 `target_query` 两个关键字参数;新增 LIKE 通配符转义辅助 `_like_contains()` |
| `apps/server/dopilot_server/api/v1/tasks.py` | `GET /tasks` 增加 `schedule_id`、`q` 两个 query 参数 + `q` 长度校验(400) |
| `apps/server/tests/test_task_filters.py`(新) | 本任务全部后端用例 |

### 前端(8 个文件)

| 文件 | 改动 |
|---|---|
| `apps/web/lib/api/types.ts` | `ListTasksParams` 增加 `scheduleId?: string \| null`、`q?: string \| null` |
| `apps/web/lib/api/tasks.ts` | `listTasks()` 透传上述两参数为 `schedule_id` / `q` |
| `apps/web/app/(app)/tasks/page.tsx` | 拆出 `TasksPageInner` 并包 `React.Suspense`;把分散的筛选 state 收敛为单一 `filters` 对象 + 唯一请求 effect;从 URL 读 `schedule_id`/`schedule_name` 初始化;新增搜索框(300ms 防抖 + 请求序号防乱序 + `maxLength`)与调度筛选芯片;请求失败兜底 |
| `apps/web/app/(app)/schedules/page.tsx` | 操作列新增「任务记录」链接 |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | 新增文案键 |
| `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx` | 新增用例(URL 初始化、防抖、竞态、长度边界、筛选保持) |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 新增入口链接用例 |
| `apps/web/lib/api/__tests__/client.test.ts` | 新增 `listTasks()` 参数序列化用例(经真实 axios 实例 + 自定义 adapter) |

### 文档(2 个文件)

| 文件 | 改动 |
|---|---|
| `docs/decisions/0023-task-target-search-without-trigram-index.md`(新) | 记录"暂不引入 pg_trgm 索引"的取舍 |
| `docs/decisions/README.md` | 索引追加一行 |

合计约 **13 个文件**(不含 `.ai/` 过程产物),超过 10 → 走 plan 评审闸。

### 明确不动的部分

- **不加迁移、不改表结构、不加索引**。`Task.target` 保持无索引(取舍见
  ADR 0023)。
- **不动 `spider` / `build_artifact_id` / `status` 三个既有过滤器**的语义
  与参数名。
- **不做 URL 全量同步**:只在挂载时**单向读取** URL 的 `schedule_id`;
  搜索词 `q`、status、build artifact、页码均为页面本地状态,不回写 URL。
  理由是回写会在每次击键/翻页触发 `router.replace`,收益(可分享链接)
  不足以抵消状态源变两处带来的复杂度。清除调度筛选时是唯一例外——
  会 `router.replace("/tasks")` 把 URL 抹掉以免刷新后筛选复活。
- **不改 `TaskSummary` / `TasksResponse` 结构**:`schedule_id` 已在
  `task_summary()` 返回(`services/executions.py:634`)。
- 不动 SSE / 日志 / 调度触发等任何既有链路。

## 实现方案

### 1. 服务层过滤(`services/executions.py`)

`list_tasks_page()` 追加两个 keyword-only 参数,与既有过滤器一样 **AND**
拼接,并同时作用于 `base` 与 `count_q`(否则 total 与行数不一致):

```python
_LIKE_ESCAPE = "\\"

def _like_contains(value: str) -> str:
    """Build a ``%value%`` LIKE pattern with wildcards escaped literally.

    Escapes the escape char FIRST, then ``%`` and ``_`` — otherwise a user's
    literal backslash would swallow the wildcard escapes we just added.
    """
    escaped = (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"
```

过滤分支:

```python
if schedule_id:
    base = base.where(Task.schedule_id == schedule_id)
    count_q = count_q.where(Task.schedule_id == schedule_id)
if target_query:
    pattern = _like_contains(target_query)
    cond = Task.target.ilike(pattern, escape=_LIKE_ESCAPE)
    base = base.where(cond)
    count_q = count_q.where(cond)
```

要点:

- **调用方传入前须 `strip()`**,服务层只把 falsy(None / 空串)当"无
  筛选";纯空白字符串由 API 层 strip 后变空串,同样落到"无筛选"。
- `ilike` 在 PostgreSQL 编译为 `ILIKE ... ESCAPE`,在 SQLite(测试库)
  编译为 `lower(x) LIKE lower(y) ESCAPE`——两端都保留 ESCAPE 子句,
  行为一致;TC-04 专门锁这一点。
- `schedule_id` 走 `ix_tasks_schedule_id_status` 的前缀列,无需新索引。
- `target_query` 是前后通配的 `%x%`,吃不到 B-tree,当前量级下走顺序扫;
  取舍写进 ADR 0023,不在本任务加索引。

### 2. API 层(`api/v1/tasks.py`)

```python
MAX_TARGET_QUERY_LEN = 100

@router.get("/tasks", ...)
async def list_tasks(
    ...,
    schedule_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    ...
):
    target_query = (q or "").strip()
    if len(target_query) > MAX_TARGET_QUERY_LEN:
        raise ApiError(
            400, "task.invalid_query", "errors.invalidQuery",
            {"max_length": MAX_TARGET_QUERY_LEN, "length": len(target_query)},
        )
```

并把 `schedule_id=schedule_id or None`、`target_query=target_query or None`
透传给服务层。校验风格对齐既有的 `task.invalid_page_size` /
`task.invalid_status`(同文件 `api/v1/tasks.py:107-124`):显式 `ApiError`
+ 400 + 稳定 code,不用 FastAPI 的 422。

**未知 `schedule_id` 不报 404**:等值匹配自然返回空页(`total=0`),这与
"调度已删除但历史任务还在"的真实场景一致;报 404 反而丢失历史任务视图。

### 3. tasks 页(`app/(app)/tasks/page.tsx`)

**Suspense 拆分**:静态导出(`output: "export"`,`apps/web/next.config.mjs`)
下 `useSearchParams` 必须位于 Suspense 边界内,否则 `next build` 直接失败。
照抄 `tasks/detail/page.tsx:337-341` 已有的写法:把现有组件体改名
`TasksPageInner`,默认导出包一层
`<React.Suspense fallback={<div data-testid="tasks-table" />}>`。该约束由
TC-18 的真实 `next build` 兜底(tsc / eslint / vitest 都验证不了它)。

**状态收敛(本节的核心改动)**:现有实现把 `page`/`pageSize`/`buildFilter`/
`statusFilter` 拆成四个独立 state,再由每个事件处理器把当前值**作为实参
快照**传进 `load()`。这个形状在引入防抖后会坏:防抖的 `setTimeout` 回调在
注册时就闭包捕获了当时的筛选值,若用户在 300ms 内又改了下拉或清了调度芯片,
回调会带着**过期的筛选组合**发请求;更糟的是它的请求序号更大,于是正确的
请求结果反被它覆盖。

因此把全部筛选收敛为**单一状态对象**,并让请求只有**一个发起点**:

```tsx
interface TaskFilters {
  page: number;
  pageSize: TaskPageSize;
  build: string;              // BUILD_ALL 或 build_artifact_id
  status: string;             // STATUS_ALL 或具体状态
  scheduleId: string | null;  // 仅挂载时从 URL 读入
  q: string;                  // 已生效(防抖后)的搜索词
}

const [filters, setFilters] = React.useState<TaskFilters>(initialFilters);
const [searchInput, setSearchInput] = React.useState(""); // 输入框受控值
const [reloadNonce, setReloadNonce] = React.useState(0);  // 「刷新」按钮
const reqSeq = React.useRef(0);
```

三条规则,合起来消灭整类竞态:

1. **任何筛选变更一律走函数式更新** `setFilters(prev => ({ ...prev, ... }))`,
   绝不读取闭包里的旧值。改筛选同时置 `page: 1`;翻页/改页大小只动
   `page`/`pageSize`。
2. **防抖回调不发请求**,只把输入框的值提交进 `filters`:

   ```tsx
   React.useEffect(() => {
     if (searchInput === filters.q) return;          // 已同步,不重复排期
     const timer = setTimeout(() => {
       setFilters((prev) => ({ ...prev, q: searchInput, page: 1 }));
     }, 300);
     return () => clearTimeout(timer);               // 输入再变则重排
   }, [searchInput, filters.q]);
   ```

   回车时直接执行同一个 `setFilters`;`filters.q` 随即改变,上面的 effect
   因守卫命中而不会再补一枪(cleanup 也已清掉待触发的 timer)。
3. **唯一请求发起点**是一个以 `filters` 为依赖的 effect,它读的永远是
   最新且**完整**的筛选组合,不存在"部分新、部分旧"的快照:

   ```tsx
   React.useEffect(() => {
     const seq = ++reqSeq.current;
     let alive = true;
     setLoading(true);
     listTasks({
       page: filters.page,
       pageSize: filters.pageSize,
       buildArtifactId: filters.build === BUILD_ALL ? null : filters.build,
       status: filters.status === STATUS_ALL ? null : (filters.status as TaskStatus),
       scheduleId: filters.scheduleId,
       q: filters.q || null,
     })
       .then((res) => {
         if (!alive || seq !== reqSeq.current) return;  // 过期响应,丢弃
         setTasks(res.tasks); /* ...其余 setState... */
       })
       .catch(() => {
         if (!alive || seq !== reqSeq.current) return;
         toast.error(t("tasks.loadFailed"));            // 不留未处理 rejection
       })
       .finally(() => {
         if (alive && seq === reqSeq.current) setLoading(false);
       });
     return () => { alive = false; };
   }, [filters, reloadNonce, t]);
   ```

**请求竞态防护**:`reqSeq` 仍然必要——effect 按序触发不代表响应按序返回,
慢的旧响应仍可能后到。序号在成功与失败两条路径上都判,过期一律丢弃。选
序号而非 `AbortController` 的理由:序号能一并覆盖"已完成但过期"与"已失败
但过期",且不必改 `lib/api/tasks.ts` 的签名去透传 signal;响应体极小,网络层
是否真取消对本页无收益。

**首屏页大小**:现有 `pickPageSizeFromHeight()` 在挂载 effect 里算出后
`setPageSize` 再 `load(...)`;收敛后改为在 `useState` 的惰性初始化里算进
`initialFilters`,避免挂载时先用默认值多打一次请求。

**长度上限**:搜索框设 `maxLength={MAX_TARGET_QUERY_LEN}`(前端常量 100,
注释指向后端 `api/v1/tasks.py` 的同名常量),使 UI 无法构造出会被后端
400 拒绝的请求;后端校验保留为独立防线(直接打 API 的调用方)。粘贴超长
文本时输入被截断到 100,请求照常成功。

**调度筛选芯片**:`filters.scheduleId` 非空时,在筛选行渲染 `<Badge>` +
一个 ✕ 按钮(`data-testid="tasks-schedule-filter-clear"`),点击后
`setFilters(prev => ({ ...prev, scheduleId: null, page: 1 }))` 并
`router.replace("/tasks")`(抹掉 URL,免得刷新后筛选复活)。芯片文案取
`schedule_name`,缺失时回退显示 `schedule_id`。

### 4. schedules 页入口

操作列在「立即触发」左侧插入:

```tsx
<Button variant="ghost" size="sm" asChild
        data-testid={`schedule-tasks-${schedule.name}`}>
  <Link href={`/tasks?schedule_id=${encodeURIComponent(schedule.id)}` +
              `&schedule_name=${encodeURIComponent(schedule.name)}`}>
    {t("schedules.viewTasks")}
  </Link>
</Button>
```

`schedule_name` 仅作芯片文案;它由 React 作为文本渲染(自动转义),且
**不会被回传给任何 API**,被篡改的后果上限是芯片显示一个错误的名字,
实际筛选仍由 `schedule_id` 决定。

### 5. 文案键

`zh.ts` / `en.ts` 各新增:`tasks.searchTargetPlaceholder`、
`tasks.scheduleFilterLabel`、`tasks.clearFilter`、`tasks.loadFailed`、
`schedules.viewTasks`。

### 6. ADR 0023

记录:目标名搜索采用 `ILIKE '%x%'` 顺序扫,**暂不引入 pg_trgm GIN 索引**。

理由不是"装不上"——本项目用 `postgres:16`,`pg_trgm` 自 PG13 起是 trusted
extension,对目标库有 `CREATE` 权限的普通角色即可安装,无需超级用户。真正的
理由是**写放大与收益方向相反**:`tasks` 是每天增长数万行的高写入表
(`services/executions.py:326`),而目标名搜索是人工低频操作;trigram GIN 的
维护成本常驻在每次写入上,收益只在偶尔搜索时兑现。次要理由:当前规模下
顺序扫足够(列表本就分页),且 `CREATE EXTENSION` 仍需该库 CREATE 权限,
在由 DBA 预建库的部署下可能失败。复议触发条件:单次列表查询 p95 超过 1s,
或 `tasks` 行数超过百万级。

## 测试用例

<!-- 全部 A 档:18 条用例均可由非交互命令判定(pytest / vitest / next build /
     ruff / eslint / tsc),无人工交互项,故 C 档为 0(上限 18/3=6)。
     前端命令一律在仓库根用 `corepack pnpm --filter web ...` 执行——仓库根
     没有 package.json(仅 pnpm-workspace.yaml:1-2 声明 apps/web),
     不带 --filter 会报 "no workspace package"。 -->

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 已建 3 个任务,其中 2 个 `schedule_id="sch-a"`、1 个 `schedule_id="sch-b"` | `.venv/bin/pytest apps/server/tests/test_task_filters.py::test_list_tasks_page_schedule_filter -v` | 传 `schedule_id="sch-a"` 时 `total == 2` 且返回行的 `schedule_id` 全为 `sch-a` | 命令 + 完整 stdout/stderr + 退出码 → `evidence/tc-01.txt` |
| TC-02 | A | 已建 `target` 为 `demo:Alpha`、`demo:beta`、`other:alpha` 的任务 | `.venv/bin/pytest ...::test_target_query_is_case_insensitive_substring -v` | 传 `target_query="ALPHA"` 命中 `demo:Alpha` 与 `other:alpha` 共 2 条;传 `"demo:"` 命中 2 条 | 同上 → `evidence/tc-02.txt` |
| TC-03 | A | 同 TC-01/02 的混合数据 | `.venv/bin/pytest ...::test_filters_and_together -v` | `schedule_id` + `target_query` + `status` 三者同时传入时按 AND 收敛,`total` 与返回行数一致(证明 count 查询同样加了条件) | 同上 → `evidence/tc-03.txt` |
| TC-04 | A(异常/边界) | 已建 `target` 为 `a%b`、`a_b`、`axb`、`ayb` 的任务 | `.venv/bin/pytest ...::test_like_wildcards_are_escaped -v` | `q="%"` 只命中 `a%b`(1 条)而非全部;`q="_"` 只命中 `a_b`(1 条);`q="a_b"` 只命中 `a_b`,不命中 `axb`/`ayb` | 同上 → `evidence/tc-04.txt` |
| TC-05 | A(异常/边界) | 库中有若干任务 | `.venv/bin/pytest ...::test_blank_query_means_no_filter -v` | `q=None`、`q=""`、`q="   "` 三者返回结果与不传筛选完全一致;`q="  alpha  "` 等价于 `q="alpha"` | 同上 → `evidence/tc-05.txt` |
| TC-06 | A | 起 `exec_client`,库中有带 `schedule_id` 的任务 | `.venv/bin/pytest ...::test_get_tasks_schedule_filter -v` | `GET /api/v1/tasks?schedule_id=<已存在>` 返回该调度的任务;`?schedule_id=nonexistent` 返回 200 且 `total == 0`、`tasks == []`(**不是 404**) | 同上 → `evidence/tc-06.txt` |
| TC-07 | A | 起 `exec_client`,库中有不同 `target` 的任务 | `.venv/bin/pytest ...::test_get_tasks_target_query_filter -v` | `GET /api/v1/tasks?q=alpha` **成功**返回过滤后的行(证明 API→服务层透传真实生效,而非只在服务层测过);`?q=alpha&status=complete` 两个筛选 AND | 同上 → `evidence/tc-07.txt` |
| TC-08 | A(异常/边界) | 起 `exec_client` | `.venv/bin/pytest ...::test_get_tasks_rejects_overlong_query -v` | `?q=` 传 101 字符 → 400 且 body 的 `code == "task.invalid_query"`;传 100 字符 → 200 | 同上 → `evidence/tc-08.txt` |
| TC-09 | A | web 测试环境 | `corepack pnpm --filter web exec vitest run --reporter=tap "app/(app)/tasks/__tests__/tasks.test.tsx"` | URL 带 `?schedule_id=sch-a&schedule_name=nightly` 时首次 `listTasks` 收到 `scheduleId: "sch-a"`,芯片显示 `nightly`;点 ✕ 后再次 `listTasks` 的 `scheduleId` 为 null 且芯片消失 | 命令 + 完整 TAP 输出 + 退出码 → `evidence/tc-09.txt` |
| TC-10 | A | 同上,`vi.useFakeTimers()` | 同一命令 | 输入 `alpha` 后 299ms 内未发请求;跨过 300ms 后 `listTasks` 收到 `q: "alpha"` 且 `page: 1`;按 Enter 时立即发请求,且随后跨过 300ms **不会**再发第二次(防抖 timer 已被清) | 同上 → `evidence/tc-10.txt` |
| TC-11 | A(异常/边界) | 同上,`listTasks` mock 返回可手动 resolve 的受控 Promise | 同一命令 | 先后触发查询 A、B(B 后发),让 **A 晚于 B** resolve;表格最终显示 B 的结果,A 的结果被丢弃(锁死请求竞态) | 同上 → `evidence/tc-11.txt` |
| TC-12 | A(异常/边界) | 同上 | 同一命令 | 向搜索框粘贴 120 字符 → input 实际值长度为 100,发出的 `q` 长度为 100(UI 无法构造出被后端 400 的请求);另:`listTasks` reject 时页面不抛未处理异常且给出错误提示 | 同上 → `evidence/tc-12.txt` |
| TC-13 | A | 同上 | 同一命令 | 设好 `q` 与 `scheduleId` 后点「下一页」/ 改页大小 / 点刷新,每次 `listTasks` 调用都仍带同样的 `q` 与 `scheduleId`(证明筛选不被翻页冲掉) | 同上 → `evidence/tc-13.txt` |
| TC-14 | A(异常/边界) | 同上,`vi.useFakeTimers()` | 同一命令 | **防抖等待期内改别的筛选**:输入 `alpha` 后不推进计时器,立即把 status 下拉改为 `failed` 并点 ✕ 清除调度芯片,再推进 300ms;最终发出的请求同时带 `q: "alpha"`、`status: "failed"`、`scheduleId: null`(证明防抖用的是最新完整筛选,而非注册时的旧快照) | 同上 → `evidence/tc-14.txt` |
| TC-15 | A | web 测试环境 | `corepack pnpm --filter web exec vitest run --reporter=tap "app/(app)/schedules/__tests__/schedules.test.tsx"` | `schedule-tasks-<name>` 链接存在,`href` 等于 `/tasks?schedule_id=<id>&schedule_name=<urlencoded name>` | 命令 + 完整 TAP 输出 + 退出码 → `evidence/tc-15.txt` |
| TC-16 | A | web 测试环境 | `corepack pnpm --filter web exec vitest run --reporter=tap "lib/api/__tests__/client.test.ts"` | 经**真实 axios 实例 + 自定义 adapter** 捕获出站请求:`listTasks({scheduleId:"s1", q:"alpha"})` 发出的 `params` 含 `schedule_id: "s1"`、`q: "alpha"`;`listTasks({})` 的 `params` **不含**这两个键(证明 camelCase→snake_case 序列化真实生效,不被页面层 mock 掩盖) | 同上 → `evidence/tc-16.txt` |
| TC-17 | A(回归) | 干净工作区;PG 并发用例需 `DOPILOT_TEST_DATABASE_URL` | 依次执行 `.venv/bin/pytest apps packages -q`、`corepack pnpm --filter web run test`、`ruff check apps packages`、`corepack pnpm --filter web run lint`、`corepack pnpm --filter web run typecheck` | 后端用例数 = 基线 782 + 本次新增且**无失败**;web 全绿且 = 基线 107 + 本次新增;三项静态检查退出码均为 0 | 五条命令各自完整输出 + 退出码 → `evidence/tc-17-*.txt` |
| TC-18 | A(构建约束) | 已装依赖 | `corepack pnpm --filter web run build` | 静态导出构建成功(退出码 0),证明 `useSearchParams` 已正确置于 Suspense 边界内——这是 tsc / eslint / vitest **都无法覆盖**的 Next 导出期约束 | 完整构建输出 + 退出码 → `evidence/tc-18.txt` |

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| `%x%` 顺序扫在大表上变慢 | 任务列表页响应变长 | 长度上限 100 + 已有分页限制单页行数;取舍与复议阈值写入 ADR 0023;真慢了单开任务上 pg_trgm |
| LIKE 通配符未转义导致 `%` 变全匹配 | 搜索结果错误 | `_like_contains()` 显式转义 + TC-04 双向锁定 |
| `ilike` 在 SQLite/PG 行为分叉 | 测试绿但生产不一致 | TC-02/TC-04 在 SQLite 测试库跑;ESCAPE 子句两端都保留,差异仅在非 ASCII 大小写折叠(`target` 实际取值为 `project:spider`,ASCII) |
| 并发请求乱序返回,旧结果覆盖新搜索 | 搜索框显示词与表格内容不一致 | `reqSeq` 请求序号丢弃过期响应(成功与失败两条路径都判序号)+ TC-11 用受控 Promise 强制乱序 |
| 防抖回调携带过期筛选快照(等待期内改了下拉/清了芯片) | 请求带旧 status/build/schedule,且因序号更大反而覆盖正确结果 | 筛选收敛为单一 `filters` 对象;防抖只做函数式 `setFilters`,**不发请求**;请求由唯一一个读最新 `filters` 的 effect 发出 + TC-14 专测该路径 |
| 前端可构造出超 100 字符的 `q` → 未处理 400 | 粘贴长文本后停在旧结果且产生 unhandled rejection | 输入框 `maxLength=100` 从源头堵住 + `load()` 加 catch 兜底提示 + TC-12 |
| API 层漏透传 / axios 参数名写错 | 页面测试全绿但线上筛选无效 | TC-07 走真实 HTTP 断言成功过滤;TC-15 绕开页面 mock 直测 `listTasks()` 出站参数 |
| 筛选状态重构后漏改某个入口 | 某个操作静默丢筛选 | 单一 `filters` 对象 + 函数式更新,使漏传某个筛选在类型层就不可能;TC-13 覆盖翻页/改页大小/刷新三条路径 |
| 静态导出下 `useSearchParams` 未包 Suspense | `next build` 失败,发布时才暴露 | 照抄 `tasks/detail/page.tsx:337-341`;**TC-18 跑真实 `next build`** 作为唯一有效验证(tsc/lint/vitest 均无法覆盖) |
| count 查询漏加新条件 | `total` 与实际行数不符,分页器页数错 | TC-03 显式断言 `total` 与行数一致 |

**回滚**:本任务无迁移、无表结构变更、无协议变更,`git revert` 单个提交
即可完全回退;回退后前端不再发送 `schedule_id`/`q`,后端即使残留也只是
两个未被使用的可选 query 参数,无兼容性负担。

<!-- 过程产物落点:体量较大的验证证据(日志)放任务目录 evidence/。 -->
