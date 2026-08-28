---
task: schedule-tasks-link-and-target-search
round: 03
date: 2026-08-28
---

# 实现记录:第 03 轮

第 02 轮评审 **VERDICT: pass**(无 blocker/major),但附带一条
**plan-blocker R-01** 与三条 minor。本轮处理这四条。

> **关于 plan-blocker 的流程说明**:rawf-review 规定"存在 plan-blocker →
> 不进入修复,转用户裁决"。本轮之所以就地修正而非停下,理由有二:
> (1) R-01 指出的是**我写进 ADR 的一个事实错误**(把 pg_trgm 说成需要超级
> 权限),把错误前提提交进 `docs/decisions/` 比任何一种决策走向都更糟,
> 必须改;(2) 修正后**决策本身未变**(仍暂缓 pg_trgm),只是换成了成立的
> 理由,这正是评审给出的两条出路之一("若仍决定暂缓,应改写 plan 与 ADR
> 的理由")。是否**改为现在就上 pg_trgm** 属架构选择,已在汇报中原样呈给
> 用户裁决,本轮不代为决定。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `docs/decisions/0023-task-target-search-without-trigram-index.md` | R-01:背景段更正——项目用 `postgres:16`(`deploy/docker/docker-compose.yml:110`),`pg_trgm` 自 PG13 起是 **trusted extension**,对目标库有 CREATE 权限的普通角色即可安装,无需超级用户;理由段重写为按权重排序的 4 条,首要理由改为**写放大与收益方向相反**(`tasks` 每天增长数万行,见 `services/executions.py:326`;而搜索是人工低频操作),原"需超级权限"降级为"仍需该库 CREATE 权限,DBA 预建库的部署可能失败"这一次要风险。R-03:影响段的决策引用由错误的 0002/0009 改为 0003(单管理员)、0004(统一镜像两种角色)、0006(FastAPI + Next 静态导出) |
| `.ai/.../plan.md` | 第 6 节 ADR 描述同步更正(同 R-01) |
| `apps/web/app/(app)/tasks/page.tsx` | R-02:芯片 ✕ 由手写 `<button>` 改为 `Button variant="ghost" size="icon-xs"`,保留 `aria-label` 与 `data-testid`;移除图标上的 `size-3`(`icon-xs` 已内置 `[&_svg:not([class*='size-'])]:size-3`,见 `components/ui/button.tsx:29`) |
| `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx` | R-04:TC-14 在恢复真实计时器后补一次 `waitFor`,让在途响应结算,消除 `TasksPageInner` 的 act 警告 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | plan-blocker | 事实已独立核实:`deploy/docker/docker-compose.yml:110` 为 `postgres:16`;pg_trgm 自 PG13 为 trusted extension。ADR 与 plan 的错误前提已删除并替换为成立的理由(见上表)。决策结论不变,是否改为现在采用 pg_trgm 交用户裁决 |
| R-02 | minor | 已改用 shadcn Button ghost/icon-xs 组合。证据:`apps/web/app/(app)/tasks/page.tsx:246-256`;`round03-tc-17-18-checks-and-build.txt` 中 eslint/tsc/build 均 EXIT=0 |
| R-03 | minor | 决策编号已逐个核对标题后更正(0002=分期、0009=实时日志,确为误引;改为 0003/0004/0006) |
| R-04 | minor | 已消除。单跑任务页用例的 act 警告数为 **0**(`round03-tc-09-to-14-tasks-tap.txt`);全量 web 套件仍有 16 条,但经 `git stash push -u -- apps/web` 后跑同一命令**基线同为 16 条**,来源为 MaintenancePage / TopControls / ThemeToggle / NotificationBell / LocaleSwitch 等既有组件,与本任务无关 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 ~ TC-08 | A | pass | `evidence/round03-tc-17-backend-pytest.txt`(全量 790 passed, 1 skipped, EXIT=0,含本文件 8 条);逐条锚点见第 02 轮 `round02-tc-01-08-backend.txt`(本轮未改动后端测试) |
| TC-09 ~ TC-14 | A | pass | `evidence/round03-tc-09-to-14-tasks-tap.txt`,16 条 TAP 全 `ok`,`not ok` 计数为 0,EXIT=0 |
| TC-15 | A | pass | 全量回归覆盖(`round03-tc-17-web-vitest.txt`,122 passed);逐条锚点见 `tc-15-schedules-tap.txt` |
| TC-16 | A | pass | 同上;逐条锚点见 `tc-16-client-tap.txt` |
| TC-17 | A(回归) | pass | `round03-tc-17-backend-pytest.txt`(790 passed, 1 skipped, EXIT=0)、`round03-tc-17-web-vitest.txt`(122 passed, EXIT=0)、`round03-tc-17-18-checks-and-build.txt` 前三段(ruff / eslint / tsc,EXIT 均 0) |
| TC-18 | A(构建约束) | pass | `round03-tc-17-18-checks-and-build.txt` 第四段,`✓ Compiled successfully`、`/tasks` 列于静态预渲染路由,EXIT=0 |

## 与方案的偏差

沿用第 01/02 轮已记录的偏差(服务层也 strip;命令用 `.venv/bin/python -m`;
证据文件按命令范围合并并逐条给锚点;PG 连接串)。本轮新增一项:

- **本轮修改了已 approved 的 plan.md**(第 6 节 ADR 描述)。原因是评审的
  plan-blocker 明确要求"改写 plan 与 ADR 的理由";改动仅限于把一个事实
  错误换成正确表述,不触及目标、范围、接口或任何测试用例。
