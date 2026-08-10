---
status: approved
task: event-stall-heartbeat
date: 2026-08-10
approved_at: 2026-08-10 18:02:25
plan_review_max_rounds: 15
impl_fix_max_rounds: 15
---

# 方案:补运行期 attempt 心跳,修复 15 分钟 event-stall 误杀长任务

> **评审轮次上限授权记录**:用户于 2026-08-10 本任务会话中明确指示
> 「plan 和改修的 review 都上升到最大 15 轮」,据此(依 CLAUDE.md 硬规则
> 的用户授权条款)在 frontmatter 写入 `plan_review_max_rounds: 15` /
> `impl_fix_max_rounds: 15`,并已在向用户的摘要中声明。

## 背景与目标

线上 `steammarket-spider` 的 `steamcommunity` 爬虫单轮需约 49 分钟,但每次
在第 15 分钟被 SIGINT 杀掉(交接调查见
`assets/handoff-15min-event-stall-kill.md`,证据完整)。根因已对照当前代码
(`b2f2ad2`)核实:

- server 的 reconcile 循环用 `last_event_at` 判定「事件停滞」,超过
  `lost_after_stalled_seconds`(默认 900)即标 `lost(event_stall)` 并发
  `stop(intent=reclaim)` 杀进程(`apps/server/dopilot_server/redis/reconcile.py:152-172`);
- 但事件类型只有 6 种生命周期状态转换
  (`packages/protocol/dopilot_protocol/streams.py:115-123`),attempt 进入
  `running` 后到自然结束前**不会再产生任何事件**,`last_event_at` 停在启动
  时刻 → 900 秒成了任务运行时长硬上限;
- agent 侧其实**每 ~5 秒就在确认进程存活**:
  `reconcile_started_attempts()`(`apps/agent/dopilot_agent/redis/commands.py:271-304`)
  对每个 started 的 scrapy attempt 调 scrapyd `listjobs`,确认仍在
  running/pending 时却什么都不发(`terminal is None → continue`);
- 影响不止 scrapy:`python_wheel` 长任务同样只在启动时发一次 `running`,
  server 侧 reconcile 不区分 runner 类型,超 15 分钟同样被 reclaim。

目标:健康的长任务不再被误杀;「事件停滞」回归其本义 ——「agent 无法确认
进程存活」才算停滞。采用交接文档的方案 B(运行期心跳,根治)+ 方案 A
(默认阈值调大,兜底),并按其 §六「落地时要确认的几点」逐条落实:
新增独立心跳事件类型(不污染状态机与审计表)、心跳频率 60s ≪ stalled
阈值 300s、**仅在确认进程真的存活时才发心跳**。

## 改动范围

### protocol(1 文件 + 测试)

- `packages/protocol/dopilot_protocol/streams.py`:`AgentEventType` 新增
  `heartbeat = "attempt.heartbeat"`;不进 `_TERMINAL_EVENT_TYPES` /
  `_AUTHORITATIVE_TERMINAL_EVENT_TYPES`。
- `packages/protocol/tests/test_stream_schemas.py`:新类型往返与属性断言。

### server(2 文件 + 测试)

- `apps/server/dopilot_server/services/events.py`:`apply_event` 在查
  `_EVENT_TO_EXEC` 之前对 `heartbeat` 分支处理(细节见实现方案 §2):
  - execution 处于 `EXEC_LOST` → 保留既有 cleanup-reconcile 保护语义,
    投递 `stop(intent=reclaim)`,状态保持 lost;去重语义为**「该
    execution 曾投递过 reclaim(任意 outbox 状态,含 sent)即不再投」**
    (心跳是 60s 周期事件,只查未决态会在首条转 `sent` 后重复投递);
    仅在**新投递**时写一条 `OUTCOME_RECLAIM_REQUESTED` 审计;
  - 其余状态 → 仅刷新 `last_event_at`、清 `stalled_at`,不走状态机、
    不做 task 回滚、**不写 event_audit 行**(避免 60s 频率把审计表撑大;
    心跳幂等,无需 dedupe)。新增模块级 outcome 常量(如
    `OUTCOME_HEARTBEAT`,仅作返回值,不落库)。
- `apps/server/dopilot_server/services/outbox.py`:新增共享查询助手
  `reclaim_ever_issued(session, execution_id)`(type=stop、
  intent=reclaim、**不过滤状态**);heartbeat 分支使用它。
- `apps/server/dopilot_server/redis/reconcile.py`:`_reclaim_issued`
  (reconcile.py:251-260,语义与新助手完全相同)改为复用
  `outbox_svc.reclaim_ever_issued`,行为零变化(消重复实现)。既有
  `_request_reclaim`(accepted/running-on-lost 路径)保持原样不动。
- `apps/server/dopilot_server/config/settings.py`:
  `lost_after_stalled_seconds` 默认 900 → 3600(方案 A 兜底:防新
  server + 旧 agent 组合下长任务仍被 15 分钟截断;有心跳后健康任务
  idle ≤ 心跳间隔,阈值放宽不影响误杀防护,仅影响真异常的回收时延)。
- `apps/server/dopilot_server/redis/consumers.py`:`EventConsumer.
  _apply_one` 对 `from_stream_entry` 解析失败(如未来未知事件类型)做
  毒丸容错 —— 记 warning 后 XACK 跳过,不再卡死整条事件流(见实现方案
  §5;仅事件消费者,本任务新事件类型落点即此)。
- `apps/server/tests/test_event_consumer.py`、`test_reconcile_redis.py`、
  `test_config.py`:对应用例见下。

### agent(4 文件 + 测试)

- `apps/agent/dopilot_agent/redis/events.py`:`EventPublisher` 新增
  `emit_heartbeat(task_id, execution_id)` —— **直接 XADD,不经持久
  outbox**(心跳是瞬时信号:Redis 断连期间落盘重放没有意义,反而会挤占
  outbox 容量、在 C5 容量上限下淘汰真正重要的终态事件;XADD 失败仅记日志
  吞掉,下一轮再发)。
- `apps/agent/dopilot_agent/redis/commands.py`:`CommandConsumer`
  - 构造参数新增 `attempt_heartbeat_interval_seconds`,内部维护
    `{execution_id: 上次心跳 monotonic 时刻}`;
  - `reconcile_started_attempts()`:scrapy attempt 经 `listjobs` 确认
    `AttemptStatus.running`(含 scrapyd pending,即本地排队非停滞)且距
    上次心跳 ≥ 间隔 → `emit_heartbeat`;status 为 `unknown`(scrapyd 不可
    达)**不发**;发出 terminal 时清掉限频记录;
  - 同一循环里对 `_inproc_wheel` 中且
    `wheel_runner.active_execution_ids()` 判定存活的 wheel attempt 同样
    限频发心跳(进程已退出则不发,终态由后台 wait 任务负责);
  - `_release_execution` 清掉限频记录。
- `apps/agent/dopilot_agent/config/settings.py`:`AgentSettings` 新增
  `attempt_heartbeat_interval_seconds: int = 60`(与
  `heartbeat_interval_seconds` 并列;须 ≪ server `stalled_attempt_seconds`
  默认 300)。
- `apps/agent/dopilot_agent/main.py`:把该配置接入 `CommandConsumer` 构造。
- `apps/agent/tests/test_command_consumer.py`、`test_config.py`
  (必要时 `test_event_outbox.py`):对应用例见下。

### 配置样例与文档(4 文件)

- `configs/server.example.toml`、`configs/server.docker.toml`:
  `lost_after_stalled_seconds` 样例值与注释同步(3600,并说明心跳后的
  语义)。
- `configs/agent.example.toml`:新增 `attempt_heartbeat_interval_seconds`
  条目与注释。
- `docs/architecture/03-execution-and-logs.md`(§事件停滞)与
  `04-configuration.md`(如列有该配置项):回写心跳语义 —— stalled/lost
  的含义从「无状态转换事件」变为「agent 无法确认进程存活」。
- `docs/architecture/05-deployment.md`:回写升级顺序操作约束(见风险
  §升级顺序:server 先行,远端 agent 确认 server 版本后再升)。

### 明确不动

- server 侧 reconcile 判定逻辑本身(`reconcile.py`)——心跳经既有
  `last_event_at` 通道生效,判定代码零改动;
- `stalled_attempt_seconds`(300)与 `heartbeat_timeout_seconds`(30)默认值;
- 六种既有事件类型的状态机语义、event_audit 既有写入路径;
- 爬虫侧(交接文档明确:steammarket-spider 无需改动);
- 上游 scrapydweb 边界(decisions/0001)不受影响。

预计触及文件 ≈ 19(> 10),**须走 plan 阶段 Codex 评审闸**。

## 实现方案

### 1. 协议:新增 `attempt.heartbeat` 事件类型

`AgentEventType.heartbeat = "attempt.heartbeat"`。`short` 属性天然得
`"heartbeat"`;`is_terminal` / `is_authoritative_terminal` 均为 False。
`AgentEvent` 模型字段不变(心跳事件仅填 event_id/agent_id/task_id/
execution_id/type/created_at)。

### 2. server:`apply_event` 分支处理心跳

在现有 dedupe 查询之前插入:

```python
if event.type == AgentEventType.heartbeat:
    execution = await svc.get_execution(session, event.execution_id)
    if execution is None:
        return OUTCOME_SKIPPED_NO_ATTEMPT     # 不写审计
    execution.last_event_at = now
    execution.stalled_at = None
    if execution.status == EXEC_LOST:
        # cleanup-reconcile 保护(评审 R2-R-01):server-lost 后 agent 恢复,
        # 心跳即「进程仍活着」的证明 -> 投递 reclaim,状态保持 lost。
        # 去重取「曾经投递过即不再投」(评审 R3-R-01):心跳是周期事件,
        # 只查未决态会在首条 reclaim 转 sent 后每 60s 重复投递。
        if not await outbox_svc.reclaim_ever_issued(session, execution.id):
            outbox_svc.create_stop_outbox(
                session, task_id=execution.task_id, execution_id=execution.id,
                agent_id=execution.agent_id or "", intent=StopIntent.reclaim,
            )
            _audit(session, event, redis_msg_id, OUTCOME_RECLAIM_REQUESTED)
        return OUTCOME_RECLAIM_REQUESTED
    return OUTCOME_HEARTBEAT                  # 不写审计
```

要点:

- 不碰状态机(`_EVENT_TO_EXEC` 对 heartbeat 无映射,分支同时避免
  KeyError)、不调 `_update_task`;非 lost 路径不写 `event_audit`。
- **EXEC_LOST 分支保留既有保护**(`events.py:200-206` 对 lost execution
  收到非终态事件投 reclaim 的语义):`heartbeat_timeout` 标 lost 时
  server 不发 stop(`reconcile.py:145-150`),agent 恢复后心跳正是
  「进程仍在跑」的最强信号,必须触发回收,否则孤儿进程永不被回收且
  `finalize_drained_logs` 的纯 server-lost 路径永远等不到 reclaim。
- **去重是持久语义**:`reclaim_ever_issued` 不过滤 outbox 状态(含
  `sent`/`failed`),与 `finalize_drained_logs` 判断「已尝试回收、可
  清理」所用的 `_reclaim_issued`(reconcile.py:251-260)完全同一语义,
  二者复用同一助手。心跳触发的 reclaim 对每个 execution **终生至多
  一条**;若 stop 送达后 agent 未能生效,兜底仍是既有
  accepted/running-on-lost 路径(其未决态去重允许重投,保持原行为)。
  命令投递本身是 Redis 消费组 at-least-once,单条即足。
- 硬 terminal(finished/failed/canceled)上的迟到心跳仅刷新
  `last_event_at`,无其他副作用(reconcile 只扫 `EXEC_ACTIVE`)。

### 3. agent:确认存活才发、限频、不落 outbox

心跳发射条件(交接文档 §六.3 的关键点 ——「我确认它还活着」而非
「我还在」):

| runner | 存活判据 | 挂载点 |
|---|---|---|
| scrapy | scrapyd `listjobs` 将该 job 列于 running/pending(`_resolve_status` 返回 `running`);`unknown`(scrapyd 不可达)不发 | `reconcile_started_attempts()` 现有 `terminal is None` 分支 |
| python_wheel | `execution_id ∈ _inproc_wheel` 且 `wheel_runner.active_execution_ids()` 含它(`returncode is None`) | 同一循环新增遍历 |

限频:`time.monotonic()` 差 ≥ `attempt_heartbeat_interval_seconds` 才发;
记录在 consumer 内存 dict,terminal 发出与 `_release_execution` 时清理
(agent 重启后 dict 归零,最多提前一拍心跳,幂等无害)。

`emit_heartbeat` 不调用 `_persist`(不落持久 outbox),XADD 异常记
warning + `status.mark_error` 后吞掉 —— 保证 reconcile 循环继续处理
其余 attempt。

### 4. 阈值调整(方案 A 兜底)

`lost_after_stalled_seconds` 默认 900 → 3600。有心跳后,该阈值的语义是
「agent 在线但连续 N 秒无法确认某 attempt 存活」,3600 在灵敏度与安全边际
间取偏保守的一侧;单管理员可按需在 `[agents]` 配置或
`DOPILOT_LOST_AFTER_STALLED_SECONDS` 覆盖(既有能力,零改动)。

### 5. 事件消费者毒丸容错(配套加固)

`EventConsumer._apply_one` 目前对 `from_stream_entry` 解析失败无逐条
容错(`consumers.py:65-71`):异常传播到 `_run` 的兜底 catch,消息不
XACK → pending 反复重投,一条坏消息即可卡死整条事件流。本任务新增事件
类型正是这类风险的第一现场,顺手加固:

```python
try:
    event = from_stream_entry(AgentEvent, fields)
except Exception:
    logger.warning("unparseable agent event %s; skipping", msg_id, exc_info=True)
    await self._redis.xack(self._stream, self._group, msg_id)
    return
```

作用域限定:仅 `EventConsumer`(本任务的变更落点);`LogConsumer` 无
schema 变更,不动。注意这只保护**升级后的新 server** 免受未来偏斜影响,
**救不了本次升级中的旧 server** —— 旧 server 的防护只能靠升级顺序
(见风险 §升级顺序)。

### 6. 已知局限(记录,不在本任务解决)

- 「进程存在但业务上僵死」(如 spider 死锁但 scrapyd 仍列 running)将不再
  被 event-stall 捕获 —— 这类检测需要日志/进度信号,与 scrapyd 自身提供的
  保证一致,留待后续按需求立项;
- 心跳刷新用 server 侧 `now`(与既有 `last_event_at` 语义一致),不使用
  事件自带时间戳。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | protocol 测试环境 | `pytest packages/protocol/tests/test_stream_schemas.py`(新增用例:heartbeat 类型 `to_stream_entry`/`from_stream_entry` 往返;`is_terminal`/`is_authoritative_terminal` 为 False;`short == "heartbeat"`) | 全部通过 | 命令 + 完整输出 + 退出码 |
| TC-02 | A | server 测试环境,一条 running execution 且 `stalled_at` 已置位、`last_event_at` 为旧值 | `pytest apps/server/tests/test_event_consumer.py`(新增用例:apply heartbeat 事件) | `last_event_at` 刷新、`stalled_at` 清空、status 仍 running;**event_audit 无新行** | 命令 + 完整输出 + 退出码 |
| TC-03 | A | server 测试环境 | 同上文件新增用例:对不存在的 execution apply heartbeat | 返回 skipped_no_attempt 语义,不抛异常、不写审计 | 命令 + 完整输出 + 退出码 |
| TC-04 | A | server 测试环境,execution `started_at` 早于 `lost_after` 阈值但刚被 heartbeat 刷新 | `pytest apps/server/tests/test_reconcile_redis.py`(新增用例) | reconcile 不标 lost、不发 reclaim;对照组(无心跳、idle 超阈值)仍正常标 lost | 命令 + 完整输出 + 退出码 |
| TC-05 | A | — | `pytest apps/server/tests/test_config.py`(断言默认值);`pytest apps/agent/tests/test_config.py`(断言 `attempt_heartbeat_interval_seconds` 默认 60、TOML 可覆盖) | `lost_after_stalled_seconds` 默认 == 3600;agent 新配置默认 == 60 | 命令 + 完整输出 + 退出码 |
| TC-06 | A | agent 测试环境(fake scrapyd client),started scrapy attempt | `pytest apps/agent/tests/test_command_consumer.py`(新增用例:listjobs 返回 running → 首轮发 heartbeat;间隔内二次调用不重发;越过间隔后再发;listjobs 返回 finished → 发 terminal 且不发 heartbeat) | 事件流中 heartbeat/终态数量与时序符合预期 | 命令 + 完整输出 + 退出码 |
| TC-07 | A | agent 测试环境,scrapyd client 抛 `ScrapydError`(不可达) | 同上文件新增用例 | status 解析为 unknown,**不发** heartbeat(不给存活不明的进程续命) | 命令 + 完整输出 + 退出码 |
| TC-08 | A | agent 测试环境,in-process wheel attempt | 同上文件新增用例:子进程存活(`returncode is None`)→ 发 heartbeat;子进程已退出 → 不发 | 心跳仅在存活时发出 | 命令 + 完整输出 + 退出码 |
| TC-09 | A | agent 测试环境,Redis XADD 抛异常 | 新增用例(`test_command_consumer.py` 或 `test_event_outbox.py`):emit_heartbeat 遇 XADD 失败 | 不抛出、reconcile 继续;**outbox 目录不产生心跳文件** | 命令 + 完整输出 + 退出码 |
| TC-10 | A | 仓库根 | `python -m pytest`(根聚合 testpaths)与 `ruff check apps packages` | 全量测试与 lint 通过,无回归 | 命令 + 完整输出 + 退出码 |
| TC-11 | A | server 测试环境,execution 已被标 `lost`(模拟 heartbeat_timeout,无既往 reclaim) | `pytest apps/server/tests/test_event_consumer.py`(新增用例:apply heartbeat;把首条 reclaim outbox 行改为 `sent`;再 apply 第二次 heartbeat) | 状态保持 `lost` 不回退;首次心跳投递一条 `stop(intent=reclaim)` 并写一条 `OUTCOME_RECLAIM_REQUESTED` 审计;首条转 `sent` 后第二次心跳**不新增** outbox 行、**不新增**审计(终生至多一条) | 命令 + 完整输出 + 退出码 |
| TC-12 | A | server 测试环境,事件流中混入一条无法解析的条目(如未知 type)后跟一条合法事件 | `pytest apps/server/tests/test_event_consumer.py`(新增用例:EventConsumer.drain_once) | 坏条目被 XACK 跳过(记 warning),后续合法事件正常应用,循环不卡死 | 命令 + 完整输出 + 退出码 |

C 档 0 条(全部可自动化判定)。证据统一存任务目录 `evidence/`。

## 风险与回滚

- **升级顺序(混布版本偏斜)**:旧 server 的事件消费者对未知事件类型解析
  失败且不 XACK(`consumers.py:65-71` 无逐条容错),新 agent 先上会让该
  消息反复重投、阻塞事件流。**必须先升 server(能识别 heartbeat 且带毒丸
  容错)再升 agent(才会发 heartbeat)**。注意统一镜像**不能**天然保证
  这一点:all-in-one compose 中 agent 仅依赖 Redis 不依赖 server 健康
  (`deploy/docker/docker-compose.yml` x-agent),远端 agent
  (`docker-compose.agent.yml`)更是完全独立。可执行顺序:
  - all-in-one:`docker compose pull` 后先 `docker compose up -d server`,
    确认 server 健康(新版本)再 `docker compose up -d`(或直接整组
    `up -d` 但须确认 server 容器成功切到新版;若 server 启动失败而 agent
    已是新版,须回滚 agent 或修复 server 后事件流自行恢复);
  - 远端 agent:一律在中心 server 确认升级完成后再拉新镜像重建;
  - 万一顺序颠倒发生卡流:完成 server 升级即自愈(新 server 可解析/跳过
    积压条目),无需清理 Redis。
  该操作约束回写 `docs/architecture/05-deployment.md`。
- **审计/存储**:心跳不写 event_audit、不落 outbox,无表膨胀与磁盘风险;
  事件流条目受既有 `maxlen_events`(approximate)约束。
- **误保活**:心跳条件绑定「scrapyd 明确列出 / 子进程 returncode 为
  None」,scrapyd 不可达或进程退出即停发,不会给僵尸续命;scrapyd 本地
  pending 队列视为健康(排队非停滞),属预期语义。
- **回收时延变长**:真异常(agent 在线但持续无法确认存活)从 15 分钟放宽
  到 60 分钟才 reclaim;单管理员可用既有配置/环境变量调回。
- **回滚**:纯增量改动 —— 回滚 agent 即停发心跳,回滚 server 即回到旧
  判定;配置默认值可用 `DOPILOT_LOST_AFTER_STALLED_SECONDS` 独立覆盖,
  无数据迁移、无 schema 变更。
