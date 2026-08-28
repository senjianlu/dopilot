---
task: log-copy-and-schedule-concurrency
date: 2026-08-28
rounds: 2
verdict: pass
---

# 任务小结:日志复制 + 定时调度并发上限

## 改动

| 文件 | 摘要 |
|---|---|
| `apps/server/dopilot_server/models/scheduling.py` | `Schedule.max_concurrency`(NOT NULL,模型默认 1) |
| `apps/server/dopilot_server/models/execution.py` | `Task` 增 `ix_tasks_schedule_id_status` 索引 |
| `apps/server/migrations/versions/0014_schedule_max_concurrency.py`(新) | 加列(`server_default="1"`,存量回填为 1)+ 建索引;`downgrade` 对称回滚 |
| `apps/server/dopilot_server/services/schedules.py` | 准入闸 `acquire_firing_slot`(行锁内:存在→启用→积压合并→并发)、`FiringSlot`、`count_active_tasks_for_schedule`、`_validate_max_concurrency`;接入 `trigger_now` / `fire_timer`;`schedule_view` 输出字段 |
| `apps/server/dopilot_server/services/outbox.py` | 注释更新:积压合并只管"未下发",并发归 0022 的闸 |
| `apps/server/dopilot_server/api/v1/schemas.py` | 三个 schema 增字段;创建/更新 schema 各挂 before-validator 拒绝 bool |
| `apps/server/tests/test_schedules.py` | 存量 `test_repeated_trigger_now_not_coalesced` 改用 `max_concurrency=0`;补默认值断言 |
| `apps/server/tests/test_schedule_concurrency.py`(新) | 19 个用例:值域/类型契约、上限边界、active/终止态、0=不限、作用域隔离、多 execution 计一次、跨来源同池、跳过日志分流 |
| `apps/server/tests/test_schedule_concurrency_pg.py`(新) | 3 个用例:并发双触发行锁、锁下重读上限、锁内 coalesce |
| `apps/server/tests/test_migration_0014_pg.py`(新) | 真实 0013→0014→0013 升级/回填/索引/回滚 |
| `apps/web/components/features/log-viewer.tsx` | 复制按钮:写当前视图缓冲、可用性预判、成功/失败 toast、空缓冲禁用、范围说明 |
| `apps/web/lib/api/types.ts` | `Schedule.max_concurrency`、`CreateScheduleRequest.max_concurrency?` |
| `apps/web/app/(app)/schedules/page.tsx` | 并发上限表单项(0 安全解析)+ 列表列(0→"不限")+ 编辑预填 + 409 toast 且不跳转 |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | 复制/并发/错误相关文案 |
| `apps/web/components/features/__tests__/log-viewer.test.tsx` | 5 个复制用例 |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 4 个并发 UI 用例 |
| `docs/decisions/0022-schedule-concurrency-limit.md`(新) | 新 ADR |
| `docs/decisions/0014-node-strategy-and-push-mode.md` | 顶部标注 coalesce 口径部分被 0022 取代 |
| `docs/decisions/README.md` | 索引新增 0022 |
| `docs/architecture/02-domain-model.md`、`06-web-frontend.md` | 回写并发上限与日志复制 |

## 评审历程

**plan 阶段**(`plan-review.sh`,19 轮,上限 20):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | 下载快照语义与 `Content-Length` 自相矛盾;证据契约未逐条声明 |
| 02 | fail | `get_current_admin` 依赖 `get_session`,流式响应会钉住数据库连接;并发用例只覆盖 limit=1 |
| 03 | fail | `maintenance._truncate_file` 会原地截断日志,"只增不减"的前提不成立 |
| 04 | fail | 并发闸用锁前读到的上限判断;Pydantic 把 `false` 收敛成 `0`(= 不限) |
| 05 | fail | 积压合并查询在锁外会漏看刚提交的积压;fd 释放与多 execution 计数无用例 |
| 06 | fail | 跳过原因用裸 `None` 表达会把禁用/积压误报为超限;`0=不限` 在 UI 上未验证 |
| 07 | fail | 存量 `test_repeated_trigger_now_not_coalesced` 与默认上限 1 冲突 |
| 08–10 | fail | fd 泄漏窗口、分块边界、`execution_id` 选取等下载侧问题 |
| 11 | fail | `logs.max_file_bytes` 可配 `0`(无上限),blob 下载会无界占用浏览器内存 |
| 12–14 | fail | 下载鉴权矩阵、HEAD 预检语义、PG 用例把节点写进了 SQLite |
| 15 | fail | 截断会写 marker,可能长度够读满而内容被改写 |
| — | — | **用户裁定移除日志下载功能**,上述下载侧问题随之全部消失 |
| 16–18 | fail | PUT 路径的 bool 未覆盖、剪贴板异常用例缺非空缓冲前置、跨来源同池未验证、迁移用例与其他 PG 用例抢库 |
| 19 | **pass** | 无问题 |

**实现阶段**(`review.sh`,2 轮,上限 20):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | R-01(blocker)TC-25 证据被 `tail -30` 截断、命令写成占位符;R-02(major)`CreateScheduleRequest` 漏 `max_concurrency` |
| 02 | **pass** | 无问题 |

## 遗留 minor 及处置

无。最后一轮评审"问题清单:无"。

## 验证结果

- 后端:`782 passed, 1 skipped`(基线 759,新增 23),含 4 个 PostgreSQL 用例
- 前端:`107 passed`(新增 9)
- `ruff check apps packages`、`eslint`、`tsc --noEmit` 均退出码 0
