---
status: approved
task: resource-hard-limits
date: 2026-07-24
approved_at: 2026-07-24 (用户确认)
plan_review_max_rounds: 10
impl_fix_max_rounds: 10
---

# 方案:资源硬上限与膨胀治理(部署层 + server + agent)

## 背景与目标

生产环境曾因容器日志与应用文件无界增长导致宿主机卡死。最新生产证据
(`docker system df -v`,2026-07-24):

- `dopilot_dopilot-redis` 卷 **2.11GB** —— 超过数据库与业务数据本身。
  成因:log stream 仅按条目数裁剪(`stream_maxlen_logs=1000000`,约 1–2KB/条
  → 1–2GB 数据集)+ AOF ≥ 数据集;`log_retention_seconds` 配置存在但无消费者
  (无任何 XTRIM 调用),`maxmemory` 未设置。
- `dopilot_dopilot-db` 卷 **1.31GB** —— `event_audit` 每条 agent 状态事件插一行,
  全库无删除路径;`tasks/executions/execution_log_files/command_outbox`
  仅有手动清理 API。
- `dopilot_dopilot-server-data` 卷 **1.508GB** —— `/server-data/logs` 无单文件
  上限、无自动保留(`[logs].retention_days` 是死配置);artifacts 只增不减。
- 三份 compose 所有服务均无 `logging:` 配置(json-file 无界)。

全仓库审计(2026-07-24,全文见任务目录 `assets/audit-inventory.md`)确认的
无界增长面共 15 项,分布在部署层(D1–D2)、server(S1–S6)、agent(A1–A7)。

**目标**:每个增长面获得可配置硬上限 + 安全默认值;过期由后台自动执行,
不依赖运维手动调 API。保持既有不变量(`docs/decisions/0009`):日志 RPO≠0
可接受、日志缺口/截断是可见审计事实(`log_integrity`)且**永不阻塞执行状态
收敛**;单实例 server(`docs/decisions/0010`)。

**范围决策**(已与用户对齐):本任务 = Phase A(部署层)+ Phase B(server)
+ Phase C(agent)止血;运维页面资源量化监控(Phase D)**紧接着另开任务**。
`docs/architecture/03-execution-and-logs.md:84` 已声称"agent 另有 TTL 兜底
GC"但代码从未实现——本任务将其补实,文档与代码对齐。

## 改动范围

### Phase A —— 部署层硬上限(仅 compose,3 个文件)

- `deploy/docker/docker-compose.yml`、`docker-compose.server.yml`、
  `docker-compose.agent.yml`:
  - 新增共享 anchor `x-logging`(json-file,`max-size: "10m"`,
    `max-file: "3"`),应用到**每个** service(server / agent×N / redis /
    db / migrate)。
  - redis 命令行追加:`--maxmemory ${DOPILOT_REDIS_MAXMEMORY:-512mb}
    --maxmemory-policy noeviction --auto-aof-rewrite-percentage 100
    --auto-aof-rewrite-min-size 64mb`。`noeviction` 是刻意选择:XADD 失败
    响亮报错而非静默逐出流数据;两侧现有代码已容忍 XADD 失败(agent 日志
    游标不前进、事件留在磁盘 outbox、server 派发重试)。

### Phase B —— server 上限 + 自动保留 + Redis/PG 膨胀治理

- **B1 单执行日志文件上限**:新增 `[logs].max_file_bytes`(默认 104857600
  = 100MB)。在消费落盘路径(`services/logs.py:88-93` →
  `logs/files.py:163-187`)强制:达上限后停止追加正文但**继续消费 + ACK**
  (不失速),追加一行可见截断标记,`log_integrity` 置新增粘滞值
  `truncated`(`models/execution.py:209`,String 无约束,**零迁移**;web
  未引用该字段,展示归 D 任务)。
- **B2 自动保留清扫**:新循环 `RetentionSweepLoop`(克隆
  `redis/reconcile.py:256-303` 模式),挂入 lifespan(`app.py:153-178`),
  间隔 `[maintenance].sweep_interval_seconds`(默认 3600),
  cutoff = now − `[logs].retention_days`——终于实装该死配置。日志定稿时写
  `retained_until`(`models/execution.py:225`,已有列)。
  **失败安全的清理顺序**:既有 `cleanup_terminal_data` 先 unlink 正文再删
  行、由调用者提交(`services/maintenance.py:133`),异常时会留下指向已删
  正文的悬空索引;自动周期执行会放大该风险,故将其重构为三步两提交:
  (1) 将命中行标记 `execution_log_files.status='expired'`(既有枚举值,
  `models/execution.py:202-205`)并 **commit**——正文缺失自此是可见审计
  事实;(2) unlink 正文,ENOENT 幂等忽略,其他 IO 失败记 ERROR 留待下
  tick 重试;(3) 删除 4 表行并 **commit**。任一步中断,下一 tick 从标记
  态幂等续作,任何时刻都不存在"未标记的悬空索引"。手动 API 与自动清扫
  走同一实现。
- **B3 event_audit 保留**:清扫循环内按
  `[maintenance].event_audit_retention_days`(默认 30)分批删除
  (每批 5000,避免长锁)。
- **B4 Redis 治理**(本次生产证据的直接回应):
  - `RedisStreams` 增加 `xtrim`(`redis/client.py`);清扫循环每 tick 对
    `LOG_STREAM` 与 `EVENT_STREAM`(`packages/protocol/dopilot_protocol/streams.py:52-54`)
    执行 `XTRIM MINID ~ <(now − log_retention_seconds)×1000>`——实装
    `[redis].log_retention_seconds`(`config/settings.py:86`,现为死配置);
    启动后首个 tick 即生效,部署当天就能收缩生产 2.11GB 数据集。
  - `stream_maxlen_logs` 默认值 1000000 → **100000**(server
    `config/settings.py:85` 与 agent 侧同步,见 C7);configs 样例同步。
- **B5 上传大小上限**:新增 `[artifacts].max_upload_bytes`(默认 209715200
  = 200MB)。现有 `ScrapyArtifactStore.save` / `WheelArtifactStore.save`
  均要求完整 `bytes` 并经 `BytesIO` 校验后二次写盘
  (`artifacts/scrapy_store.py:75-146`、`wheel_store.py:60-134`),仅改
  endpoint 无法实现内存有界,因此**store 层新增基于路径的接口**
  `save_from_path(tmp_path, …)`:endpoint 分块读(1MB)写入 artifacts
  staging 目录下的临时文件,**边读边流式累计 sha256** 与字节数,超限即
  413;store 对临时文件直接执行 `ZipFile` 校验与元数据解析,zip/hash/文件
  操作全部经 `asyncio.to_thread` 下沉线程池(项目异步边界);校验通过后
  `os.replace` 同卷原子发布正文、再写 manifest;一切失败路径(413/校验失败
  /IO 异常)`finally` 清理临时文件,不留残留。旧的 bytes 入口保留为薄壳
  或删除,以两个 endpoint 均改走新路径为准。
  **聚合总量配额**(用户裁决,round-03 R-01):新增
  `[artifacts].max_total_bytes`(默认 21474836480 = 20GiB,0 = 不限)。
  准入检查 = 现有总量(DB 内两类 artifact `size_bytes` 求和,事务一致)
  + 在途预留 + 本次声明/实测大小;超配额返回 **507**,提示需运维清理或
  调大配额。并发安全:单实例 server(决策 0010)内以模块级
  `asyncio.Lock` 保护"查总量 + 记在途预留",staging 落盘后按实测大小
  复核一次,发布或失败后释放预留。产品决策"归档不自动删除"不受影响
  ——配额满时**拒绝新上传**而非回收旧件。
- **B6 SSE 队列有界**:`logs/sse.py:27` 订阅队列改
  `asyncio.Queue(maxsize=1000)`。仅从注册表移除**不能**唤醒阻塞在
  `queue.get()` 的生成器(`api/v1/tasks.py:382`),因此满载断开机制为:
  `put_nowait` 触发 `QueueFull` 时,**清空该队列积压后投入 CLOSE 哨兵**
  (清空后必有空位)并从注册表 unsubscribe;生成器收到 CLOSE 即结束,
  `finally` 走既有清理路径。`publish`/`close` 对已移除的订阅幂等、不抛错。
  客户端按既有恢复路径重连续传。
- **B7 配置一致性**:`retention_days` 默认统一为 30(代码
  `config/settings.py:150` 现为 14,`configs/server.docker.toml` 为 30)。

### Phase C —— agent janitor + 上限

- **C1 janitor 循环**(实装文档已承诺的 TTL 兜底 GC):周期任务(默认
  600s,启动时先跑一次):删除**终态**执行超过 `completed_log_ttl_days`
  (默认 3)与**孤儿**超过 `orphan_log_ttl_days`(默认 7)的
  workspace/日志/state;修复 `_handle_cleanup`(`redis/commands.py:660-672`)
  漏删 `.logpos` 游标文件的缺陷,并清扫 `state/logpos/` 存量泄漏。
  **孤儿判定的安全边界**(`StateStore.read()` 在文件缺失/损坏/校验失败时
  均返回 `None`,`state/store.py:190-211`,不能等同"已死"):
  - **活跃集 = 纯内存运行集**:`PythonWheelRunner._procs` 在管 id ∪
    CommandConsumer 在途处理 id。`StateStore.list_execution_ids()` 只枚举
    `state/executions/*.json` 文件名(`state/store.py:236`),不区分运行/
    终态/可读性,**不得**作为活跃判据(否则损坏 state 永远"活跃"、永远
    无法回收);
  - 子进程 spawn 成功、取得 pgid 后,原子写(tmp + rename)workspace 内
    `job.pgid` sidecar(新增),使进程存活判定不依赖 state JSON 完好;
  - 删除一个"无可读 state"的 workspace 须**同时**满足:执行不在内存
    活跃集;`job.pgid` 存在则 `os.killpg(pgid, 0)` 判死(存活即跳过,
    sidecar 缺失视同"无法证活",继续看静默期);目录树**静默期** ≥
    `orphan_log_ttl_days`(树内最新 mtime 早于阈值——存活进程持续写
    job.log 会刷新 mtime,构成第二重保险);
  - 三条件齐备即删(损坏 state 因此**可回收**,不会永久滞留);删除全程
    持 `_handle_cleanup` 同一把 per-execution 锁;任何一项不满足 → 本轮
    跳过,留待下轮再判。运行中执行在任何路径下永不删除。
- **C2 job.log 大小上限**:新增 `[agent].max_job_log_bytes`(默认 100MB)。
  现架构下子进程 stdout/stderr 直接绑定 job.log 文件描述符
  (`runners/python_wheel.py:145-169`),runner 无法截断子进程的后续写入,
  因此**改造 I/O 拓扑**:子进程改为 `stdout=PIPE`(stderr 并入 stdout),
  每执行配一个异步 **drain 任务**持续读管道——限额内追加 job.log;越界时
  写一次截断标记;其后**继续排空但丢弃**(保证管道永不填满、进程永不因
  背压阻塞)。drain 生命周期:随 spawn 启动、进程退出后排空至 EOF 再关闭
  文件、由 reaper await、`aclose()` 统一取消回收;drain 内异常只记日志,
  永不影响进程与状态上报;其簿记条目纳入 C6 终态清理。
- **C3 scrapyd 保留显式化**:生成的 `scrapyd.conf`
  (`scrapyd/process.py:100-114`)显式写入 `jobs_to_keep` /
  `finished_to_keep`,经 `[scrapyd]` 配置暴露(默认 5 / 100 = scrapyd
  现行内置默认)。
- **C4 artifact/wheel 缓存 LRU 淘汰**:新增
  `[agent].artifact_cache_max_bytes`(默认 2GiB,0 = 不限)。janitor 按
  `.ready` mtime(命中时 touch)LRU 淘汰超限 sha 目录
  (`artifacts/cache.py`、`artifacts/wheel_cache.py:65-83`),运行中引用的
  artifact 不淘汰。
- **C5 事件 outbox 上限**:新增 `[redis].event_outbox_max_files`(默认
  100000)。超限丢弃**最旧**文件并记 ERROR(`redis/events.py:91-129`);
  被丢事件由 server reconcile 的 lost 判定兜底。
- **C6 内存终态清理**(生命周期分两档,用户裁决 round-03 R-02):
  - **终态 + EOF 发布后即移除**:`_inproc_wheel`(`commands.py:117`)与
    `PythonWheelRunner` 各簿记 dict/set(`runners/python_wheel.py:84-89`,
    含新增 drain 簿记)——这些不承担跨 tick 去重职责。
  - **随 state 清理同步移除**:`LogPublisher._eof_sent`(`redis/logs.py:56`)
    与 `CommandConsumer._locks`(`commands.py:107`)。`publish_attempt()`
    (`redis/logs.py:130-147`)对仍在盘上的终态 state 依赖 `_eof_sent`
    去重,终态时立即移除会导致后续每个 tick 重发 EOF;故仅当
    `_handle_cleanup`(cleanup_logs)或 janitor 删除该执行的 state+logpos
    时同步移除去重条目与锁——幂等与扫描源同生命周期,内存有界性由
    janitor TTL(≤ 数天)保证。
- **C7 agent 配置面**:`maxlen_logs` / `maxlen_events`(现为构造器硬编码,
  `redis/logs.py:44`、`redis/events.py:69`)接入 `[redis]` TOML + env,
  默认与 server 对齐(logs 100000 / events 100000);上述所有新旋钮进
  `configs/agent.example.toml` 与 env 映射(照 server loader 模式)。

### 文档回写与收尾(与代码同一提交)

- `docs/architecture/04-configuration.md`:全部新增配置项。
- `docs/architecture/05-deployment.md`:compose 日志轮转、redis
  maxmemory、生产收缩 runbook(见"风险与回滚")。
- `docs/architecture/03-execution-and-logs.md`:`log_integrity` 增加
  `truncated` 值;"手动清理"表述更新为"自动保留 + 手动 API 兜底"。
- 新增 `docs/decisions/0019-resource-hard-limits.md`:上限策略与
  noeviction / drop-oldest 取舍记录。
- 旧治理流程遗留草稿 `docs/phases/task-resource-hard-limits/00-proposal.md`
  已按用户指示于 plan 阶段删除(未跟踪文件,内容已并入本 plan 与
  `assets/audit-inventory.md`),实现阶段无此项工作。

### 明确不动

- `apps/web` 一律不动(Phase D 另开任务;web 未引用 `log_integrity`,
  新枚举值零影响已验证)。
- artifact 正文不自动删除(产品决策:归档仍可运行,`services/artifacts.py:242`);
  聚合有界性由 B5 总量配额的**拒绝新上传**实现,不引入回收。
- 无 Alembic 迁移、无协议破坏性变更;Postgres 服务端调优、宿主机
  logrotate/journald 属运维指引,不入代码。
- 预计触及文件约 35–45(compose 3 + server ~15 + agent ~12 + configs 4 +
  tests ~10 + docs 5)→ **必须过 plan 评审闸**。

## 实现方案

实现顺序 A → B → C → 文档,每 phase 一个 implementation-round 内的独立小节。

关键技术点:

1. **B1 截断语义**:上限检查在 `apply_log_event` 落盘前,按"当前文件大小 +
   本增量"判定;截断后仍推进 `last_pulled_offset` 记账(保持与 agent 游标
   一致),仅不写正文。`truncated` 粘滞:一旦置位不回退(同 `partial` 语义,
   `models/execution.py:206-208` 注释)。
2. **B4 XTRIM MINID**:stream ID 高位即毫秒时间戳,minid =
   `(now_epoch_ms − log_retention_seconds*1000)`。fakeredis 对 MINID 支持
   不确定 → 单测用 stub client 断言调用参数(仓库测试已有 RedisStreams
   stub 先例),集成路径靠 TC-15 冒烟。已消费(XACK)条目被裁剪无副作用;
   未消费条目超 24h 本身已是故障态,裁剪与既有 RPO≠0 决策一致。
3. **B2/B3 清扫循环**:与 `RedisReconcileLoop` 平级新类,单 tick 内依次
   (a) terminal 数据清理 (b) event_audit 分批删 (c) 两条 stream XTRIM;
   任一步失败记 ERROR 跳过,不中断循环;慢 tick 跳过不排队。
4. **B5 流式落盘**:endpoint `while chunk := await file.read(1MB)` 累计
   字节数并流式喂 `hashlib.sha256`,超限 `raise HTTPException(413)`;临时
   文件落 `{artifacts.root_dir}/staging/`(与最终目录同卷,保证
   `os.replace` 原子);store 的 `save_from_path` 在 `to_thread` 中完成
   `ZipFile(tmp_path)` 校验、元数据解析与发布;endpoint/新接口所有失败
   路径 `finally` unlink 临时文件。TC-06 以受控 fake `UploadFile`(无
   size 参数的 `read()` 调用即失败)断言实现不会回退成全量读。
5. **C1/C2 wheel 执行生命周期**:spawn 顺序 = 建 workspace → 起子进程
   (`stdout=PIPE`)→ 取得 pgid → **原子写 `job.pgid`**(tmp + rename)
   → 起 drain 任务。**sidecar 写入失败** → `killpg` 终止进程组、按既有
   失败路径上报 failed 并回收簿记——不允许存在"运行中但无 sidecar"的
   状态。reaper 顺序 = `wait()` → await drain 至管道 EOF → 关闭 job.log
   → 上报退出码 → C6 终态簿记清理。janitor 终态判定以 state JSON 状态 +
   文件 mtime 为准;"无可读 state"路径按 Phase C/C1 的三重安全条件
   (内存活跃集、pgid 存活、树静默期)处理,任何不确定即跳过。
6. **C4 淘汰安全性**:淘汰前对 sha 目录取 `.lock`(既有锁文件机制),
   与正在进行的安装/复用互斥;当前运行执行引用的 sha 集合从
   `StateStore.list_execution_ids()` 对应 state 取得。
7. **配置加载**:server 新增 `[maintenance]` section(`sweep_interval_seconds`
   / `event_audit_retention_days` / `enabled`,默认 true);全部新字段同时
   接 TOML 与 env(`config/loader.py` 既有映射模式),
   `configs/server.example.toml`、`server.docker.toml`、
   `agent.example.toml` 同步。

## 测试用例

C 档 0 条(无人工交互项)。A 档证据(命令 + 完整输出 + 退出码)落
`evidence/`;B 档引用带 `文件:行号`。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | server 单测环境,`max_file_bytes` 设小值(如 4KB) | pytest:向同一执行连续 apply 日志增量直至超限 | 文件字节数 ≤ 上限+标记行;截断标记恰一行;`log_integrity=truncated`;后续增量仍被 ACK(消费不失速) | pytest 输出,`evidence/tc01-*.txt` |
| TC-02 | A | 同 TC-01,执行已截断 | pytest:注入 terminal 事件走定稿流程 | 执行收敛到真实终态;`truncated` 粘滞不被定稿覆盖 | pytest 输出 |
| TC-03 | A | 单测环境,构造过期/未过期 terminal 任务与日志文件;可注入 unlink / SQL / commit 故障 | pytest:驱动清扫循环单 tick(注入时钟);分别注入三类故障后再驱动下一 tick | 正常路径:过期任务的 4 表行 + 磁盘文件被删,未过期保留,`retained_until` 定稿时已写。故障路径:任一步失败后**不存在未标记 expired 的悬空索引**(正文缺失的行必已标记);下一 tick 幂等续作至删净 | pytest 输出 |
| TC-04 | A | event_audit 预置 >1 批过期行 + 未过期行 | pytest:驱动清扫 tick | 过期行分批全删,未过期保留;单批 ≤ 5000 | pytest 输出 |
| TC-05 | A | stub RedisStreams | pytest:驱动清扫 tick,校验 xtrim 调用 | 对 LOG_STREAM 与 EVENT_STREAM 各调 `xtrim(minid=now−retention)`,minid 计算正确(毫秒) | pytest 输出 |
| TC-06 | A | 上传端点测试客户端,`max_upload_bytes` 设小值;fake `UploadFile`(不带 size 的 `read()` 即抛错) | pytest:上传超限 egg 与 wheel;再上传合法小文件;校验失败文件 | 超限返回 413 且 staging 无残留、无入库行;读取始终按限定 chunk(fake 未抛错且 `read` 被多次调用);合法上传经 `save_from_path` 成功;校验失败路径临时文件被清理 | pytest 输出 |
| TC-07 | A | SSE 订阅队列 maxsize 设小值;真实驱动流生成器 | pytest:发布超过 maxsize 的日志事件而不消费;随后对已断开订阅再 publish/close | 队列被清空并收到 CLOSE 哨兵;**生成器在超时内真正结束**且 `finally` 清理完成;订阅从注册表移除;后续 publish/close 幂等不抛错;发布方全程不阻塞 | pytest 输出 |
| TC-08 | A | 伪造 agent workdir 树:终态>3d、终态<3d、运行中(在内存活跃集)、孤儿(无 state)>7d 且 pgid 已死、**state 损坏 + pgid 已死 + 静默期已满**、**state 损坏但 `job.pgid` 进程存活**、**无 state 但树 mtime 新鲜**、存量 .logpos | pytest:janitor 单 tick(注入时钟,stub `os.killpg`) | "终态>3d"、"孤儿三条件齐备>7d"、**"损坏 state 三条件齐备"均被删**(损坏 state 可回收、不永久滞留);运行中、新终态、pgid 存活者、mtime 新鲜者一律保留;.logpos 随属主清理 | pytest 输出 |
| TC-09 | A | wheel runner 单测,`max_job_log_bytes` 设小值(如 8KB) | pytest:子进程输出**远超管道容量**(≥ 若干 MB)后正常退出 | 进程不因背压阻塞、在超时内退出且退出码正常上报;job.log ≤ 上限+恰一行截断标记;drain 排空至 EOF 后文件句柄关闭 | pytest 输出 |
| TC-10 | A | — | pytest:渲染 scrapyd.conf(默认与自定义 `[scrapyd]` 保留值) | conf 含 `jobs_to_keep`/`finished_to_keep`,取值正确 | pytest 输出 |
| TC-11 | A | 伪造缓存目录:多 sha 不同 mtime,总量超 cap;其一被运行中执行引用 | pytest:janitor 淘汰逻辑 | 按 LRU 淘汰至 ≤ cap;被引用 sha 不淘汰;cap=0 不淘汰 | pytest 输出 |
| TC-12 | A | outbox 目录预置超限 .json 文件 | pytest:再 emit 一条事件 | 最旧文件被删至上限内,新事件落盘;记 ERROR 日志 | pytest 输出 |
| TC-13 | A | — | pytest:server `[maintenance]`/`[logs]`/`[artifacts]`/`[redis]` 与 agent 全部新字段,TOML 与 env 双通道 + 默认值(含 `retention_days=30`、`stream_maxlen_logs=100000`) | 加载值与优先级正确 | pytest 输出 |
| TC-14 | A | 本机 docker compose v2 | 脚本:对 3 份 compose 跑 `docker compose config`;grep 断言每个 service 含 `max-size` 且 redis 命令含 `maxmemory`/`noeviction`/`auto-aof-rewrite` | config 全部通过;断言全中 | 脚本 + 输出,`evidence/tc14-*.txt` |
| TC-15 | A | — | `pytest apps/server/tests apps/agent/tests packages/protocol/tests` + `ruff check apps packages` 全量 | 全部通过,无回归 | 完整输出 + 退出码 |
| TC-16 | B | 实现完成 | 核对文档回写与死配置实装 | 04-configuration/05-deployment/03-execution-and-logs 含新内容(引用 文件:行号);`retention_days`/`log_retention_seconds` 有消费点(代码 文件:行号);旧 `docs/phases/` 草稿已删除 | 代码/文档引用清单 |
| TC-17 | A | agent 单测:可驱动执行走 finished / failed / canceled 三种终态;state 尚在盘上 | pytest:各终态路径断言簿记容器;**EOF 后连续驱动多个 publisher tick**;再执行 cleanup/janitor 删 state;重复投递终态与 cleanup | EOF 发布前不提前清理;终态+EOF 后 `_inproc_wheel` 与 runner 各 dict/set(含 drain 簿记)移除该 id 而 **`_eof_sent`/`_locks` 仍保留**;后续多个 tick **EOF 只发一次**;state+logpos 被清理时 `_eof_sent`/`_locks` 同步移除;重复终态/cleanup 幂等不抛错 | pytest 输出 |
| TC-18 | A | 上传端点测试环境,`max_total_bytes` 设小值;可并发发起上传 | pytest:总量临界处上传恰好放行与恰好超限各一次;两个并发上传合计超配额;配额=0 | 超配额返回 507 且 staging/DB 无残留;并发下至多一个成功(预留互斥生效);配额=0 不限制;既有总量统计与 DB `size_bytes` 求和一致 | pytest 输出 |

## 风险与回滚

- **maxmemory(512mb)< 生产现有约 2GB 数据集**:部署新版后、首个清扫 tick
  的 XTRIM 生效前,Redis 可能已超限导致 XADD 报错(noeviction)。缓解:
  runbook 规定先起 server(XTRIM 于 60s 内收缩数据集)再对 redis 应用
  maxmemory(或接受首分钟的 XADD 失败——agent 侧可容忍,日志补传)。
  AOF 文件收缩靠 `auto-aof-rewrite-*` 参数 + runbook 中一次性
  `BGREWRITEAOF`。
- **noeviction 满载 → XADD 失败 → 日志缺口**:接受(RPO≠0,决策 0009);
  可观测(ERROR 日志 + 心跳 outbox 计数)。
- **PG 大清理后磁盘不立即回缩**:行删除后空间由 autovacuum 复用,文件不
  回缩;runbook 注明可选停机 `VACUUM FULL`。表行数与体积的持续可见性由
  Phase D 任务提供。
- **janitor 与在途执行竞态**:只删终态/孤儿,删除全程持 per-execution 锁;
  TC-08 覆盖运行中不删。
- **fakeredis 对 XTRIM MINID 支持不确定**:单测走 stub 断言参数(TC-05),
  不依赖 fakeredis 行为。
- **容器日志轮转丢弃旧 stdout 历史**:接受;需要留存的运维方自行外接
  日志采集。
- **回滚**:零 DB 迁移、全部新配置有默认值——回滚 = 回退镜像 + 回退
  compose 文件;`truncated` 值旧代码按未知字符串处理不崩溃(web 未引用,
  server 仅写不读枚举)。

<!-- 过程产物落点:体量较大的验证证据(日志、截图)放任务目录 evidence/,
     引用素材(Design 稿、参考图)放 assets/;二者须在评审前落盘。 -->
