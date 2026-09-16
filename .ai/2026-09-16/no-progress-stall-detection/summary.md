---
task: no-progress-stall-detection
date: 2026-09-16
rounds: 5
verdict: pass
---

# 任务小结:无活动(无进度)卡死探测 + 取消升级到 KILL

## 背景一句话

2026-09-15 一个 SWAPGG 730 job 在 Scrapy 关闭阶段卡死:日志彻底静默,但 scrapyd
仍把它列为 running,于是 agent 每 60s 照发心跳、server 永远判不了 stalled,该调度
唯一的并发槽被占了两小时。人工取消也只发一次 TERM 就立刻判 canceled 并释放槽位,
进程很可能根本没死。问题记录见
`.ai/2026-09-15/stuck-scrapy-job-holds-schedule-slot/`。

## 做了什么

**一、server 能区分「还活着」与「在干活」**

心跳现在携带 `log_bytes`(agent 每 tick 读到的 job.log 大小)。server 用两套独立时钟
记录:`last_progress_at`(日志真的变长,或来了真实生命周期事件)与
`last_progress_sample_at`(最近一次拿到**任何**读数)。只有当采样仍新鲜、且空转超过
阈值时,才打一次性标记 `no_progress_at` 并发 `attempt_no_progress` 通知。

**安全底线:这条链只告警,绝不判 lost。** `last_event_at` 与 reclaim 链一行未改,
所以长时间安静的正常任务最坏只收到一条通知 —— 这正是 steammarket-spider
`decisions/0044` 废弃 `CLOSESPIDER_TIMEOUT` 时踩过的坑。`auto_stop_on_no_progress`
默认 **false**,要真的取消得显式开启。

**二、取消 / 回收真的确认进程死了**

`stop` 不再在命令消费者里等待(那是串行的,一批取消会冻结所有执行的心跳)。改为
**先把意图落盘**,再由 tick 循环推进 TERM → 10s → KILL → 确认退出。确认用的是只问
死活的 `is_job_alive`,不是 `status` —— 后者在 TERM 之后会把离开列表的 job 报成
`canceled`(agent 自己造的,不是权威终态),且对「已取消、无日志的 pending job」同样
返回 `unknown`。

**终态有界,回收不封顶**:硬期限只约束**终态上报**;到点进程仍活着时,终态照报,但
`kill_pending` 与 scrapyd job 映射都保留,持续重发 KILL 直到确认退出。先删映射再谈
回收就等于亲手制造一个没人看得见的残留进程 —— 那正是本任务要消灭的东西。

## 改动

共 **27 个文件**(20 改 + 7 新增)。

| 层 | 文件 | 摘要 |
|---|---|---|
| 协议 | `packages/protocol/…/streams.py` | 心跳携带 `log_bytes` 的语义(字段已存在) |
| agent | `state/store.py` | 7 个 stop 状态机字段;`mark_done` 支持把 done + result + `kill_pending` + `terminal_pending` **一次原子写入** |
| agent | `runners/scrapyd.py` | 新增 `is_job_alive()`(三态:活着 / 确认不在跑 / 不可知) |
| agent | `redis/events.py` | `emit_heartbeat(log_bytes=…)`;`republish_current` 在停止期间静默 |
| agent | `redis/commands.py` | 日志采样与 flood 开关解耦;`_stop_watchdog` / `_reclaim_watchdog` / `_run_deferred_cleanup`;`_handle_cleanup` 拆出 `_do_cleanup` 并支持延期 |
| agent | `config/settings.py`、`main.py` | 三个 stop 配置 |
| server | `models/execution.py` + `migrations/0015_*` | 三个 nullable 进度列 |
| server | `services/events.py` | 心跳的进度语义(读数增长才算进度;无读数一律不动) |
| server | `redis/reconcile.py` | 无进度检测第 3 步;lost 分支加 `continue` |
| server | `config/settings.py`、`models/notification.py` | 三个配置 + 新通知类型 |
| 配置 | `configs/server.example.toml`、`configs/agent.example.toml` | 六个新键 + 风险注释 |
| web | `notification-bell.tsx`、两个 locale | 新通知的落地路由与中英文案(区分「只是告警」与「已自动取消」) |
| docs | `architecture/03-execution-and-logs.md`、`04-configuration.md` | 取消时序、无进度探测、停止状态机、终态有界/回收不封顶、配置清单 |
| 测试 | 6 个新文件 + 2 个既有适配 | 45 条用例,详见实现记录 |

## 评审历程

### plan 阶段(上限 8,用满 8 轮)

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | 进度信号有效性、一次性副作用、**取消在串行命令消费者里等待会阻塞所有执行的心跳** |
| 02 | fail | plan-blocker:确认期间到达的 `cleanup_logs` 会删掉停止状态机;reclaim 不能复用 cancel 的终态;TERM 发出前必须先落盘意图;日志采样不能挂在 flood 开关下 |
| 03 | fail | state 缺失时 cancel 的必达契约不能退化成忽略;期限检查必须先于 unknown 分支;延期清理缺重启恢复入口 |
| 04 | fail | 停止期间重投的 run 命令会绕过状态机上报被污染的 `canceled` |
| 05 | fail | plan-blocker:超时后删除映射会再次制造无法追踪的残留进程 |
| 06 | fail | cleanup 挂起条件漏了 `kill_pending`;`done` + `kill_pending` 必须原子写入;一条验收与设计自相矛盾 |
| 07 | fail | 终态落盘与投递之间的崩溃窗口无恢复路径;`status` 的 `unknown` 分不清「不可达」与「已消失」 |
| 08 | **pass** | 无 |

### 实现阶段(上限 8,用 5 轮)

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | reclaim 重投绕过幂等检查(major);lost 之后仍跑无进度检测,可能同时下发 reclaim 与 cancel(major);多条 A 档用例的测试比声明窄(blocker) |
| 02 | fail | 记录仍与源码矛盾:TC-10 实际在直接改 DB 字段、TC-42 没建日志;TC-31/43 场景不完整;缺 workspace 删除断言 |
| 03 | fail(见下) | — |
| 04 | fail | TC-22 的异常路径其实没被覆盖:注入的 `ConnectError` 被转成返回值,走的是 TC-21 的路径 |
| 05 | **pass** | 无 |

> 第 03 轮实际 pass;第 04 轮是我补完 `04-configuration.md` 与 agent 配置样例后
> 主动重送审(让评审指纹与工作区一致),结果反倒查出了 TC-22 的缺口。

两个阶段的轮次上限都按用户 2026-09-16 的明确要求放宽为 8。

## 与方案的偏差(详见 implementation-round-01.md)

1. 测试文件数比 plan 预计多(多出真实 Alembic 升降级与跨应用交付测试)
2. `_stop_watchdog` 改为**先探存活、再补发信号**:plan 写的顺序会向已经退出的 job
   多发一次 KILL,与 plan 自己的 TC-18 冲突
3. `_cleanup_must_wait` 比 plan §4.5 多一个 `terminal_pending` 条件(与 §4.7 的三条
   前置一致;终态没进 `emit` 就清理会把 `result` 一起删掉)
4. 三条既有 agent 用例适配跨 tick 收尾(预期结果未改,只多推进一个 tick)
5. 未给三个新 server 配置加环境变量覆盖(plan 未要求,守住范围)

## 遗留 minor 及处置

无。最后一轮评审问题清单为空。

## 上线提示

默认配置下本次改动**不会自动杀任何任务**:`auto_stop_on_no_progress = false`,
无进度只发通知。建议先用告警模式观察一段时间,确认没有正常任务被误报
(`no_progress_stall_seconds` 默认 1800s,明显宽于 SWAPGG 730 的 5~21 分钟),
再决定是否开启自动取消。

取消行为有一处可感知的变化:任务在 UI 上停留在 running 的时间可能多几十秒,因为
agent 现在会确认进程真的退出后才上报 `canceled`(最长 `stop_confirm_timeout_seconds`,
默认 120s)。这是「确认尸体」的必要成本。
