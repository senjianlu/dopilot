---
task: redis-log-stream-oom-investigation
date: 2026-08-22
status: investigated
type: incident-investigation
scope: 生产 console(pve-cz-console, 192.168.10.226)2026-08-21 12:10 UTC 起内存耗尽卡死
next: 改修走 rawf 流程另开 plan(本目录仅为调查与证据归档)
---

# 生产 console 内存暴涨卡死事故调查

> 时间均为 UTC;括号内为北京时间(UTC+8)。
> 证据文件在 `evidence/`,复现脚本在 `assets/`(脚本不含任何凭据)。

## 一句话结论

**被 OOM 杀死的是 Redis,不是 dopilot-server。** steammarket-spider 因表结构变更
(`prices` 表的唯一约束与 `ON CONFLICT` 不匹配)每个 item 批次都失败,SQLAlchemy
把整条带上千行 VALUES 的 INSERT 原文(单行 1.15MB)写进 scrapy 日志;agent 的
LogPublisher 对 scrapyd 运行没有任何字节上限,把日志以 256KB/条的粒度不限速推进
`dopilot:server:logs` 流;server 侧虽有 100MiB/执行落盘上限,但"丢弃"发生在
**消费之后**,字节已经进了 Redis 内存;流的 MAXLEN=100000 是按条数算的,在
256KB/条的情况下等效上限 ≈ 35GB,形同虚设。Redis 在 40 分钟内从 ~0.3GB 涨到
~7.8GB,12:10 首次被 OOM kill;此后 `restart: unless-stopped` + AOF 让 Redis 每次
重启都重新加载同一份 7GB 数据并再次被杀,**15 小时内 399 次 OOM kill**,把宿主机
拖死,直到 8/22 03:12 重启。

## 时间线

| 时间(UTC) | 事件 | 证据 |
|---|---|---|
| 8/20–8/21 11:30 | console 内存稳定 1.70GB | `prom-console-mem-used-gb-30m.txt` |
| 11:30:00 | 调度下发 run → agent-01,task `380765bc…` / execution `7e52e209…`(steammarket-spider) | `rdb-commands-summary.txt` |
| 11:30:27 | 该执行第一条 ERROR:`psycopg.errors.InvalidColumnReference: there is no unique or exclusion constraint matching the ON CONFLICT specification` | `serverlog-7e52e209-first-error.txt` |
| 11:31 | server 侧该执行日志文件触顶 100MiB(开跑仅 1 分钟),写入截断标记;agent 继续推送 | `serverlog-7e52e209…-head-tail.txt` 尾部 |
| 11:31 → 12:02 | console 已用内存以 ~130MB/分钟线性上涨:1.70 → 8.12GB(当时 VM 仅 8GB) | `prom-console-mem-used-gb-1m-0821T11-12.txt` |
| 11:40 → | agent-01 CPU 13% → 55%(scrapy 报错 + base64 推送);agent-02 无变化 | `prom-agents-cpu-0821.txt` |
| 11:45 / 12:00 | 又两个 steammarket 执行(`77455002…` agent-01,`69a7ee96…` agent-02)各在 1 分钟内触顶 100MiB | 同上 |
| 12:10:14 | **首次 OOM kill:redis-server**(rss 5.83GB + swap 2GB);dopilot-server 仅 ~200MB | `console-journal-first-oom-block-0821T1210.txt` |
| 12:10:28–31 | server 判定活动执行 lost,下发 `stop reclaim` + `cleanup_logs`(Redis 已死,agent 收不到) | `rdb-commands-summary.txt` |
| 12:10 → 8/22 03:11 | Redis 被反复拉起 → 加载 AOF 到 ~7GB → 再被杀,**共 399 次**,全部是 redis-server | `console-journal-oom-kills-0821T1210-0822T0319.txt` |
| 16:00 | 再有两个 steammarket 执行触顶 100MiB(server 间歇存活) | `serverlog-68c3466b…` / `7b98eb54…` |
| 8/22 03:12 | 宿主机挂死重启 | journal boots 列表 |
| 03:17 → 03:19 | 重启后 2 分钟内 Redis 加载 AOF 再次 OOM(同一死循环) | `console-journal-boot-0317-kernel-oom.txt` |
| 03:20 | 再次重启(VM 内存已扩到 16GB);Redis 完整加载,RDB 记录 `used-mem = 9.27GB` | `rdb-scan-keys.txt` aux 字段 |
| 03:26 | 容器被删除(`/opt/dopilot` mtime 03:26,推测为人工 `compose down`),volume 保留 | `docker ps -a` / `docker volume ls` |

## Redis 里到底是什么(离线解析 dump.rdb,未加载到任何 Redis)

`dump.rdb` 1.6GB,Redis 7.4.10,保存时 used-mem **9.27GB**,共 8 个 key,全是 stream:

| key | 条数 | 内存逻辑占用 | 累计写入 | 说明 |
|---|---|---|---|---|
| `dopilot:server:logs` | **100000**(正好 MAXLEN) | **7.95GB** | 3,463,952 | 平均 79KB/条;最老 entry 8/21 03:43(24h XTRIM 在工作,但对小时级暴涨无意义) |
| `dopilot:agent:agent-01:commands` | 100002 | 69MB | 165,707 | 命令流只有 MAXLEN,无时间截断 |
| `dopilot:agent:agent-02:commands` | 100002 | 69MB | 165,965 | 同上 |
| `dopilot:server:agent-events` | 53393 | 20MB | 1,123,085 | |
| `dopilot:agent:dopilot-agent-0/1/2/01:commands` | 100006/100004/…/2 | ~70MB ×3 | | **旧 agent id 残留**,最后写入 7 月,永不清理(~210MB 浪费) |

日志流按 execution 抽样(1/10 listpack,`rdb-logs-stream-sample.txt`):

| execution | task | 推算日志原始字节 | 平均每条 |
|---|---|---|---|
| `7e52e209…` | `380765bc…` | **≈3.05GB** | ≈251KB(= agent `max_bytes` 262144) |
| `77455002…` | `adace404…` | **≈1.82GB** | |
| `69a7ee96…` / `68c3466b…` / `7b98eb54…` | | ≈0.3–0.4GB 各 | |
| 其余 3298 个 execution | | 每个 < 1MB | 正常运行的日志量级 |

即 **两个执行占了 Redis 内存的 60% 以上,五个执行占 75%+**;其余 3000 多个执行合计不到 1GB。

## 日志为何这么大

`serverlog-7e52e209-error-stats.txt`:100MiB 文件仅 **6220 行、91 条 ERROR**,
最长行 **1,148,055 字节**。每条 ERROR = scrapy `Error processing {item}` + 两层
traceback + `[SQL: INSERT INTO prices (...) VALUES (...), (...), ... ON CONFLICT (...) DO UPDATE ...]`
(上千行 VALUES,参数编号到 `_m1335`)+ `[parameters: {...}]`。
**每次批量 flush 失败 ≈ 1.15MB 日志**,pipeline(`app/pipelines/commonPriceBatch.py:146 _flush`)
每批失败后继续下一批,spider 不退出,持续约 40 分钟。

根因在爬虫项目侧:`prices` 表结构变更后,`ON CONFLICT (market_code, app_id,
steam_market_hash_name, provider_code, market_currency_code)` 对应的唯一约束不存在。
这属于 steammarket-spider 仓库,不在本仓库范围,但本仓库的防线应当挡住它。

## "重试机制"的真相

dopilot **没有执行级失败重跑**:`command_outbox.max_retry=10` 只针对"XADD 投递失败"
重试投递,不会重新执行爬虫。看到的"大量失败"来自调度频率本身:命令流统计
steammarket-spider 在 10:00–11:59 每小时 **~690 次 run**(≈11.5 次/分钟,各为独立
task/execution),每次新调度都重现同一错误。五个巨型执行也都是各自的定时任务
(11:30、11:45、12:00、16:00×2),不是重试。12:10 Redis 死后 server 判 lost 并
下发 `stop reclaim`,因 Redis 不可用 agent 根本收不到,agent-01 的 spider 自行跑完。

## 本仓库的防线为何全部失效(改修切入点)

1. **agent LogPublisher 无字节上限、无限速**(`apps/agent/dopilot_agent/redis/logs.py`):
   每 tick `while True` 把本地 job.log 全部可读字节按 256KB/条推完为止。agent 侧
   `max_job_log_bytes=100MiB` 只在 python_wheel runner 生效,**scrapyd 运行完全没有上限**
   (`runners/scrapyd.py` / `scrapyd/process.py` 无任何 size/truncate 逻辑)。
2. **MAXLEN 按条数,对日志流无意义**:`stream_maxlen_logs=100000`,
   `config/settings.py:85` 注释假设"~1-2KB/entry → 100-200MB",实际单条最大 ≈350KB
   (256KB base64 后),**等效上限 ≈ 35GB**。需要按字节(或按 execution)约束。
3. **server 100MiB 落盘上限是"消费后丢弃"**(`services/logs.py` `OUTCOME_TRUNCATED_DROPPED`):
   设计上"keeps consuming + ACKing, never stalls",但 XACK 不释放内存,且没有任何
   反馈让 agent 停止 tail 该执行(没有 "stop_logs"/反压命令)。丢弃发生在 Redis 之后。
4. **生产 Redis 无 `--maxmemory`、无容器内存限制**:生产 `/opt/dopilot/docker-compose.yml`
   (7/31)早于仓库 a19985d(7/24 之后的版本已带 `--maxmemory 512mb --maxmemory-policy
   noeviction` 与 json-file 日志轮转),生产从未同步;镜像用的是
   `rabbir/dopilot-with-deps:latest`(8/10 构建 ≈ HEAD fe97927),compose 却是旧的。
   见 `prod-opt-dopilot-docker-compose.yml` 与 `deploy/docker/docker-compose.server.yml` 差异。
5. **AOF + `restart: unless-stopped` = OOM 死循环**:被杀后重启立刻重放 7GB,再被杀,
   399 次;宿主机整夜 thrash,最终挂死。即使加了 maxmemory,也要考虑启动加载阶段
   超限的行为(Redis 加载 RDB/AOF 不受 maxmemory 约束)。
6. **旧 agent id 的命令流永不清理**(`dopilot-agent-0/1/2/01`,~210MB),命令流只有
   MAXLEN 无时间截断;次要但应一并处理。
7. **监控盲区**:Prometheus 的 redis-exporter 只接了 cache/tencent,dopilot 的 Redis
   没有指标,无告警;node_exporter 在 12:02 之后采样大面积缺失(主机已卡)。

## 证据清单

| 文件 | 内容 |
|---|---|
| `evidence/console-journal-oom-kills-0821T1210-0822T0319.txt` | 399 条 `Out of memory: Killed … (redis-server)` + oom-kill cgroup 行 |
| `evidence/console-journal-first-oom-block-0821T1210.txt` | 首次 OOM 的完整内核块(Mem-Info + Tasks state:redis 5.83GB rss,dopilot-server ~200MB) |
| `evidence/console-journal-boot-0317-kernel-oom.txt` | 8/22 03:17 重启后 2 分钟内再次 OOM 的内核块 |
| `evidence/prom-console-mem-used-gb-30m.txt` / `-1m-0821T11-12.txt` | console 已用内存 48h 曲线 / 11:00–12:40 分钟级曲线(11:31 起涨) |
| `evidence/prom-agents-cpu-0821.txt` | agent-01/02 CPU,agent-01 11:40 起 55% |
| `evidence/prod-opt-dopilot-docker-compose.yml` | 生产 compose 原文(.env 未归档) |
| `evidence/rdb-scan-keys.txt` | dump.rdb 全量 key 统计(条数/逻辑字节/consumer group) |
| `evidence/rdb-logs-stream-sample.txt` | 日志流按 execution/task/agent 抽样分布 |
| `evidence/rdb-commands-summary.txt` | 命令流解码:每小时 run 次数、五个巨型执行的 run/stop/cleanup 命令 |
| `evidence/serverlog-<execution>-head-tail.txt` ×5 | 五个 100MiB 日志文件的头 6KB / 尾 3KB(telnet 密码已脱敏) |
| `evidence/serverlog-7e52e209-error-stats.txt` | 行数、级别直方图、错误类型计数、最长行 |
| `evidence/serverlog-7e52e209-first-error.txt` | 第一条完整错误块 + ON CONFLICT 子句 + INSERT 目标表 |
| `assets/rdbscan.py` | 流式 RDB v9–v12 解析器(按长度跳过,不加载;支持 stream listpack 抽样) |
| `assets/cmdscan.py` | 基于 rdbscan 解码命令流 |
| `assets/promq.py` | Prometheus range query 小工具 |
| `assets/rssh.py` | paramiko 远程执行助手(密码走环境变量) |

未归档(体积过大,留在本机 job 临时目录,随 job 删除):完整 journal(13MB)、
`rdb-commands-decoded.json`(117MB)、`dump.rdb`(1.6GB)。生产机上的临时副本 `/tmp/rdb-analysis/` 已清理。

## 现场状态(截至 8/22 06:5x UTC)

- console:dopilot 三个容器已删除,volume `dopilot_dopilot-db` / `-redis` / `-server-data` 保留;
  内存 16GB,负载空闲。**不要直接 `up`**:Redis volume 里仍是那份 7.9GB 的日志流,
  起来就会重演(即使 16GB 也只是暂时扛住,下一个坏 spider 同样打穿)。
- Redis volume 内另有 3.5GB 失败的 `temp-*.rdb` 残片可清理。
- server-data volume `logs/` 2.7GB。
- agent-01/02 侧未登录(只拿到 console 凭据),本地 job.log 原件(≥3GB)尚在与否未确认。
