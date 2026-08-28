---
task: schedule-tasks-link-and-target-search
date: 2026-08-28
rounds: 4
verdict: pass
---

# 任务小结:调度→任务记录快速查看 + 任务页目标名模糊搜索

## 改动

| 文件 | 摘要 |
|---|---|
| `apps/server/dopilot_server/services/executions.py` | `list_tasks_page()` 增加 `schedule_id`(等值,吃已有 `ix_tasks_schedule_id_status`)与 `target_query`(`ILIKE '%…%'`)两个过滤维度,两者同时作用于行查询与 count 查询;新增 `_like_contains()` 转义用户输入的 `%` `_` 与转义符本身;`target_query` 在服务层内 `strip()` |
| `apps/server/dopilot_server/api/v1/tasks.py` | `GET /tasks` 增加 `schedule_id`、`q` 两个 query 参数;新增 `MAX_TARGET_QUERY_LEN = 100`,`q` 超长返回 400 `task.invalid_query`;未知 `schedule_id` 返回空页而非 404 |
| `apps/server/tests/test_task_filters.py`(新) | 8 条后端用例(服务层 5 + API 层 3),含通配符转义、空白/边缘空格查询、未知 id、超长 q 四条边界 |
| `apps/web/app/(app)/tasks/page.tsx` | 六个筛选收敛为单一 `filters` 对象 + 唯一请求 effect;300ms 防抖(回车立即)、`maxLength=100`、`aria-label`;可清除的调度筛选芯片;请求失败 toast 兜底;`React.Suspense` 包裹以满足静态导出 |
| `apps/web/app/(app)/schedules/page.tsx` | 操作列新增「任务记录」链接,跳 `/tasks?schedule_id=<enc>&schedule_name=<enc>` |
| `apps/web/lib/api/tasks.ts`、`types.ts` | `ListTasksParams` 增加 `scheduleId` / `q`,序列化为 `schedule_id` / `q`,falsy 时整键不发送 |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | 新增 5 个文案键 |
| `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx` | 新增 10 条用例(下钻 3 + 搜索 7),含防抖 299/300ms 边界、防抖窗口内改其它筛选、响应乱序、长度上限、失败兜底 |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 新增 2 条:入口链接 href、名称需转义时的 URL 编码 |
| `apps/web/lib/api/__tests__/client.test.ts` | 新增 3 条:经真实 axios 实例断言出站 `params` 键名与省略行为 |
| `docs/decisions/0023-...md`(新)、`docs/decisions/README.md` | ADR:暂缓 pg_trgm 的取舍(首要理由为高写入表的写放大)、长度上限与转义、复议阈值 |
| `docs/architecture/06-web-frontend.md` | 回写两个新功能,并记录"单一 filters 对象 + 唯一请求 effect"这一实现约束的**原因** |

**不含**数据库迁移、表结构或协议变更。回滚 = `git revert` 单个提交。

## 验证

- 后端全量:790 passed, 1 skipped(基线 782,本次 +8)
- web 全量:122 passed(基线 107,本次 +15)
- ruff / eslint / tsc / `next build` 均 EXIT=0;`/tasks` 正常静态预渲染
- 18 条 plan 用例全部 A 档、全部 pass,原始输出落 `evidence/`
- 额外做了 3 次**变异验证**(见 `round02-mutation-check.md`、
  `round04-mutation-check.md`),证明关键断言并非空跑

## 评审历程

plan 阶段 3 轮(上限 10),实现阶段 4 轮(上限 10),均由用户指定放宽。

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan-01 | fail | 4 major:异步请求缺乏"仅最新生效"机制;前端未处理后端 100 字符上限;测试在适配层两侧都 mock,无法证明参数真正贯通;前端命令在仓库根不可执行且未验证静态导出构建 |
| plan-02 | fail | 1 major:防抖回调可能携带**过期的筛选快照**发起请求,且因序号更大反而覆盖正确结果 |
| plan-03 | pass | 无问题 |
| impl-01 | fail | 1 blocker:TC-05 / TC-10 / TC-14 的实际断言弱于 plan 契约却记为 pass(按证据契约属虚报) |
| impl-02 | pass | 但带 1 **plan-blocker**:ADR 中"pg_trgm 需超级权限"是错误前提(PG16 下它是 trusted extension)+ 3 minor |
| impl-03 | fail | 1 blocker:TC-11 断言存在"提前通过窗口"——检查一个本就不存在的元素,可在旧 Promise 回调前通过 |
| impl-04 | pass | 仅 1 minor(见下) |

### 评审真正拦住的实质问题

1. **防抖 + 并发请求的两类竞态**(plan-01 R-01、plan-02 R-01):这是本任务
   唯一的真实功能性隐患,直接决定了页面状态管理的形状(单一 `filters` 对象 +
   唯一请求 effect)。
2. **测试贯通盲区**(plan-01 R-03):页面层 mock 掉 `listTasks` 后,camelCase →
   snake_case 的序列化无人验证。补的 TC-07/TC-16 正是为此。
3. **三次"断言弱于契约却记 pass"**(impl-01、impl-03):这是我自己的问题,
   评审两次拦下。后续每次改完都补做变异验证自证。
4. **ADR 的事实错误**(impl-02):我把 pg_trgm 说成需要超级权限。核实后
   `postgres:16` 下它是 trusted extension,普通角色有库 CREATE 权限即可安装。
   决策(暂缓)不变,但理由已换成成立的那条。

## 遗留 minor 及处置

| 编号 | 内容 | 我的判断 | 用户决定 |
|---|---|---|---|
| impl-04 R-01 | 芯片清除按钮内的 `<X />` 未加 `data-icon="inline-start"` | **疑似误报,待裁决**。依据:(1) `.agents/skills/shadcn/rules/icons.md:9` 的规则明确是给**图标 + 文字**的前缀/后缀用的(`inline-start`/`inline-end`),此处是**纯图标按钮**,没有可"前缀"的文字;(2) 仓库内 8 处 `data-icon` 用法**全部**是图标 + 文字,无纯图标先例;(3) 全仓库**没有任何 CSS 规则消费** `data-icon`(已 grep `globals.css` 与 `components/ui/`),加它不产生任何视觉效果。按 rawf-review 规则不自行"解释掉",原样呈交 | 待定 |

## 需要用户拍板的一件事(来自 impl-02 的 plan-blocker)

ADR 0023 决定**暂缓** pg_trgm 索引。原先写的理由("需超级权限")是错的,已更正;
现在的首要理由是:`tasks` 每天增长数万行,trigram GIN 的写放大常驻在每次写入上,
而目标名搜索是人工低频操作,为低频读给高频写加常驻税方向不对。

**若你认为应该现在就上 pg_trgm**,这是一个独立的小任务(纯增量迁移:
`CREATE EXTENSION` + 建 GIN 索引,查询语句一个字都不用改),不影响本次改动。
