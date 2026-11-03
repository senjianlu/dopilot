# 0025:调度熔断代替永久停用,熔断态与 enabled 分开存

- 日期:2026-11-03
- 背景:[0021](0021-log-flood-guard-and-auto-disable.md) §6 规定同一调度连续出错达
  `auto_disable_after_errors`(默认 5)即 `enabled=false`,只能人工重新启用。它为
  拦住日志洪泛类坏爬虫而设,但判错只有一位信号(`execution_is_erroneous`),
  出口抖动、上游限速、周末市场变薄这类会在数小时内自愈的瞬态失败也会触发。
  2026-10-31 两条调度因此被停,上游很快恢复,调度却断了 35~40 小时,只因没人
  手动启用;同期全站 24 小时 14,494 轮、失败 0.39%、最长连续失败 2——系统平时
  健康,但任何一次几分钟的出口抖动都能让一条每分钟调度停上几天。历次停用复盘
  显示大多数由瞬态引起,真正需要人工的(上游改版、套餐到期、额度耗尽)反而与之
  混在同一个"连续 5 次"里。此外停用写在 `enabled` 上,与爬虫仓库声明式同步每次
  发版 `PUT enabled=<toml>` 打架:不发版一直停,一发版被原样拉起。脱敏证据见
  `.ai/2026-11-03/schedule-circuit-breaker/assets/`。

- 决定:
  1. **熔断代替永久停用,且从不修改 `enabled`**。`schedules` 新增
     `breaker_state`(`closed`/`open`/`half_open`/`held`)、`breaker_level`、
     `breaker_opened_at`/`retry_at`/`escalated_at`、`breaker_reason`、
     `breaker_artifact_id`(迁移 0016)。`enabled` 只由人和声明式同步修改。
  2. **结果分类**。对出错执行:server 自身判据(`log_flood`、`size-cap`/`dir-budget`
     截断、上限 > 0 时上报 `log_bytes` 达上限)一律 `broken`,守住 0021 的初衷;
     平台侧故障(`lost`、`dispatch_unavailable`、`dispatch_timeout`)→ `transient`;
     爬虫在最后一个 scrapy stats 块写的 `'outcome/class' == 'transient'` →
     `transient`(agent 透传为 `AgentEvent.outcome_class`,协议可选字段,上线顺序
     无依赖);其余一律 `broken`(缺键 = 与 0021 同口径)。任务级另有 `ok`
     (`complete` 且未出错)与 `neutral`(`canceled`/`no_target` 且未出错)。
  3. **跳闸**。阈值沿用 `auto_disable_after_errors`(键名保留以免破坏部署,0 = 永不
     跳闸),只对已启用的调度:连错前缀全为 `broken` → `held`(需人工,记下触发
     任务所用制品);否则 → `open`。
  4. **半开试跑**。`open` 按 `min(base × 2^level, max)` 退避(默认 900 → 1800 →
     3600 → 7200 秒),到点后在定时闸里(所有其它闸放行之后,schedule 行锁内)转
     `half_open`、代际 + 1,本次触发即试跑,与试跑任务同一次建单提交。试跑期限
     = `max`,到期无结果时同代际再放行一次(不算失败、不升级)。试跑 `ok` →
     `closed`;`transient` → `open` 且 `level + 1`;`broken` → `held`;`neutral` →
     `open` 且立即可重试。`open`/`held` 期间任一当前代际 `ok`(在途旧任务或手动
     trigger-now)即 `closed`。trigger-now 不受熔断闸限制。
  5. **需人工态的放行是拉取式的**。`held` 记 `breaker_artifact_id`;定时闸持锁读取
     模板当前已提交的 `build_artifact_id`,不同即放行一次 `level=0` 的半开试跑。
     模板服务不碰调度行,因此不存在"进入 held 与换制品"的提交顺序漏洞,也不新增
     跨行批量加锁。
  6. **复位**。`POST /schedules/{id}/breaker/reset` 与 `enabled` 假→真都回到
     `closed`、代际 + 1、清零(复位对 `closed` 无操作);两者及 `update_schedule`
     均先对 schedule 行 `FOR UPDATE` 并锁内重读。
  7. **通知分级**。`schedule_breaker_open`(warning;熔断持续 ≥
     `breaker_escalate_after_seconds`(默认 86400,0 = 不升级)后,下一次试跑失败时以
     error 再发一次,`escalated=true`)、`schedule_breaker_held`(error)、
     `schedule_breaker_closed`(info,人为复位不发)。熔断通知在 SAVEPOINT 里写,
     失败不中止结果记录事务。`schedule_auto_disabled` 不再产生,前端保留历史渲染。
  8. **不再 reload 调度器**。熔断在触发时判定,结果记录器与 reconcile 循环不再回调
     `ScheduleRunner.reload()`(否则每次熔断都会重排全部 interval 任务的相位)。

- 后果:
  - 0021 §6 的"达阈值即 `enabled=false`"被取代;其账本、代际与按次数计数机制保留。
  - 真坏却被爬虫标成 `transient` 的调度会持续失败试跑(退避等待最长 2 小时,实际
    间隔还受原触发周期与其它准入闸限制),靠 24 小时升级通知兜底。
  - 依赖"出错即 `enabled=false`"的外部脚本会看到 `enabled` 保持为真。
  - 0025 之前被自动停用的调度保留 `enabled=false` 与 `auto_disabled_*`,迁移不动,
    由人手动启用。
  - 回滚:镜像回滚前先 `alembic downgrade 0015`(删除熔断列);旧镜像恢复
    `enabled=false` 式自动停用。
  - 相关:[0021](0021-log-flood-guard-and-auto-disable.md)、
    [0022](0022-schedule-concurrency-limit.md)(并发闸先于熔断闸判定)。
