---
status: approved
task: disable-all-schedules
date: 2026-08-10
approved_at: 2026-08-10 18:43:23
plan_review_max_rounds: 10
impl_fix_max_rounds: 10
---

# 方案:调度页新增「一键停用全部」按钮(升级前操作)

> **评审轮次上限授权记录**:本方案预计触及 9 文件(≤ 10),plan 评审闸
> 本不强制;用户于 2026-08-10 本任务会话中明确指示「走下 plan review 吧,
> 一样都是最大 10 轮」,据此执行 plan 评审并在 frontmatter 写入
> `plan_review_max_rounds: 10` / `impl_fix_max_rounds: 10`
> (依 CLAUDE.md 硬规则的用户授权条款),已在摘要中声明。

## 背景与目标

dopilot 升级前需要先停掉所有定时调度(如 event-stall-heartbeat 任务要求的
「先升 server 再升 agent」窗口期),目前只能在调度页逐行拨 Switch。目标:
调度页头部新增「一键停用全部」按钮,点击弹确认框(复用既有
`useConfirm`/AlertDialog),确认后一次性停用所有已启用的调度并刷新列表。

服务端配套一个批量端点(单事务 + 单次 runner reload),不由前端逐条
PUT——逐条循环既不原子(中途失败留下半开状态),也会触发 N 次
APScheduler reload。

## 改动范围

### server(3 文件 + 测试 1 文件)

- `apps/server/dopilot_server/services/schedules.py`:新增
  `disable_all_schedules(session) -> int`——单条批量
  `UPDATE schedules SET enabled=false WHERE enabled`,返回受影响行数
  (列级 `onupdate` 的 `updated_at` 随 Core UPDATE 生效);新增
  `count_enabled_schedules(session) -> int`(不受 limit 影响的
  `COUNT(*) WHERE enabled`,评审 R2-R-01)。
- `apps/server/dopilot_server/api/v1/schemas.py`:新增
  `ScheduleDisableAllResponse { disabled: int }`;`SchedulesResponse`
  增加 `enabled_total: int`(全局已启用总数,加法变更向后兼容)。
- `apps/server/dopilot_server/api/v1/schedules.py`:新增
  `POST /schedules/disable-all`(admin 鉴权,与既有端点同
  `get_current_admin` 依赖):调服务函数 → commit → `_reload_runner`
  一次 → 返回 `{disabled: N}`。路径与既有 POST 端点无冲突。
  `GET /schedules` 填充 `enabled_total`。
- `apps/server/tests/test_schedules.py`:新增用例(见测试表)。

### web(5 文件 + 测试 1 文件)

- `apps/web/lib/api/types.ts`:`SchedulesResponse` 增加
  `enabled_total: number`。
- `apps/web/lib/api/schedules.ts`:`listSchedules` 改为返回完整
  `SchedulesResponse`(唯一调用方是调度页,同步更新);新增
  `disableAllSchedules(): Promise<{ disabled: number }>`
  (`POST /schedules/disable-all`)。
- `apps/web/app/(app)/schedules/page.tsx`:CardAction 区(创建/刷新旁)
  新增按钮 `data-testid="schedule-disable-all"`,文案
  `schedules.disableAll`;**按钮可用性与确认文案数量一律取服务端
  `enabled_total`,不再从已加载列表推断**(列表默认截断 200 条,评审
  R2-R-01);`enabled_total === 0` 或请求在途时 disabled;点击 →
  `confirm({ destructive: true, message: confirmDisableAll(enabled_total) })`
  → 确认后调 API → `load()` 刷新;取消则不发请求。
- `apps/web/lib/i18n/locales/zh.ts`、`en.ts`:新增
  `schedules.disableAll`(「一键停用」/"Disable all")与
  `schedules.confirmDisableAll`(带 `{{count}}` 的确认文案,说明用途为
  升级前止血、可逐条重新启用)。
- `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx`:新增用例
  (见测试表;沿用现有 mock 与 `confirm-accept`/`confirm-cancel` 交互
  惯例,`renderWithProviders` 已含 ConfirmProvider);既有 mock 随
  `listSchedules` 返回形状同步调整。

### 明确不动

- 不新增「一键恢复」:停用前各调度的 enabled 状态不留存快照,恢复由
  管理员逐条开启(单管理员场景数量有限;若未来需要可另立任务);
- 调度行级 Switch、CRUD、trigger-now 行为不变;
- Playwright e2e 不新增(单元层已覆盖交互与 API 合同,冒烟走既有脚本)。

预计触及文件 10(≤ 10,plan 评审闸本不强制;应用户要求执行,上限见
frontmatter 授权记录)。

## 实现方案

### 1. server 批量端点

```python
# services/schedules.py
async def disable_all_schedules(session: AsyncSession) -> int:
    result = await session.execute(
        update(Schedule).where(Schedule.enabled.is_(True)).values(enabled=False)
    )
    return int(result.rowcount or 0)

# api/v1/schedules.py
@router.post("/schedules/disable-all", response_model=ScheduleDisableAllResponse)
async def disable_all(request, _admin, session) -> ScheduleDisableAllResponse:
    disabled = await svc.disable_all_schedules(session)
    await session.commit()
    await _reload_runner(request)   # 一次 reload,APScheduler 清空 job 集
    return ScheduleDisableAllResponse(disabled=disabled)
```

幂等:重复调用第二次返回 `{disabled: 0}`,无副作用。

reload 语义的验收(评审 R-01):端点测试向 `app.state.schedule_runner`
注入 fake runner(计数的 async `reload()`),断言成功路径恰 await 一次
——「job 集清空」由既有 runner 层职责保证(reload 只注册
`list_enabled_schedules`,phase 2.2 已有测试),端点层只需精确验证
触发了一次同步。

### 2. web 按钮与确认框

```tsx
// enabledTotal 来自 GET /schedules 的 enabled_total(全局 COUNT,
// 不受列表 200 条截断影响,评审 R2-R-01)
const [enabledTotal, setEnabledTotal] = React.useState(0);

async function onDisableAll() {
  const ok = await confirm({
    title: t("confirm.title"),
    message: t("schedules.confirmDisableAll", { count: enabledTotal }),
    confirmText: t("confirm.confirm"),
    cancelText: t("confirm.cancel"),
    destructive: true,
  });
  if (!ok) return;
  setDisablingAll(true);
  try {
    await disableAllSchedules();
    await load();
  } finally {
    setDisablingAll(false);
  }
}
```

按钮 `disabled={enabledTotal === 0 || disablingAll}`,请求在途显示
Spinner(沿用页面既有样式)。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | server 测试环境,已建 2 个 enabled + 1 个 disabled 调度 | `pytest apps/server/tests/test_schedules.py`(新增用例:POST /schedules/disable-all) | 200 且 `{"disabled": 2}`;随后 GET /schedules 全部 `enabled == false` | 命令 + 完整原始输出 + 退出码 |
| TC-02 | A | server 测试环境,无任何 enabled 调度(边界) | 同上文件新增用例:直接调 disable-all,再重复调一次 | 两次均 200 且 `{"disabled": 0}`,无异常 | 命令 + 完整原始输出 + 退出码 |
| TC-03 | A | web 测试环境,列表含 enabled 调度 | `corepack pnpm --filter web test`(新增用例:点按钮 → `confirm-accept`) | `disableAllSchedules` 恰被调用 1 次,列表 `listSchedules` 重新加载 | 命令 + 完整原始输出 + 退出码 |
| TC-04 | A | 同 TC-03 | 新增用例:点按钮 → `confirm-cancel`(取消路径) | `disableAllSchedules` **未被调用** | 命令 + 完整原始输出 + 退出码 |
| TC-05 | A | web 测试环境,`enabled_total: 0`(边界) | 新增用例:断言按钮 `disabled` | 按钮不可点,点击不弹确认框 | 命令 + 完整原始输出 + 退出码 |
| TC-06 | A | 仓库根 | `python -m pytest` + `ruff check apps packages` + `corepack pnpm --filter web test` + `corepack pnpm --filter web run typecheck` + `corepack pnpm --filter web run lint` | 全部通过,无回归 | 命令 + 完整原始输出 + 退出码 |
| TC-07 | A | server 测试环境,`app.state.schedule_runner` 注入可计数的 fake runner(async `reload()`),2 个 enabled 调度 | 同 TC-01 文件新增用例:POST /schedules/disable-all | 批量停用成功后 fake runner 的 `reload()` **恰被 await 一次**(评审 R-01:验证「停掉实际定时任务」的同步动作,而不只是 DB 行) | 命令 + 完整原始输出 + 退出码 |
| TC-08 | A | web 测试环境,`disableAllSchedules` mock 为可控 pending Promise | 新增用例:点按钮 → 确认;在 Promise 未 resolve 期间再次点击按钮;随后 resolve | 在途期间按钮 `disabled`;二次点击后 API 仍**只被调用 1 次**;resolve 后列表重新加载、按钮恢复(评审 R1-R-02) | 命令 + 完整原始输出 + 退出码 |
| TC-09 | A | server 测试环境,session 层直插 201 条调度:最旧 1 条 enabled,其余 200 条 disabled(超出列表截断的边界,评审 R2-R-01) | 同 TC-01 文件新增用例:GET /schedules | 返回 `schedules` 恰 200 条且全部 `enabled == false`,但 `enabled_total == 1`(全局计数不受截断影响) | 命令 + 完整原始输出 + 退出码 |
| TC-10 | A | web 测试环境,mock 列表全部 disabled 但 `enabled_total: 1`(截断场景) | 新增用例:断言按钮**可点**;点击 → 确认 → API 被调用 | 按钮可用性取 `enabled_total` 而非已加载列表(评审 R2-R-01) | 命令 + 完整原始输出 + 退出码 |

C 档 0 条。证据统一落任务目录 `evidence/`。

## 风险与回滚

- **无恢复快照**:一键停用后不记录此前哪些是 enabled,恢复靠逐条开启。
  已在确认文案中明示;单管理员 + 调度数量有限,接受(如需「一键恢复」
  另立任务)。
- **与行级 toggle 并发**:批量 UPDATE 为单事务,与单行 PUT 最后写入者
  胜,无一致性风险(升级窗口期本就由单管理员操作)。
- **runner 同步**:端点复用既有 `_reload_runner`,与单行 update 相同的
  同步语义;若 server 未启 scheduler(`[scheduler].enabled=false`)则
  reload 为 no-op,行为不变。
- **回滚**:纯增量(新端点 + 新按钮),回滚提交即可,无 schema/配置
  变更。
