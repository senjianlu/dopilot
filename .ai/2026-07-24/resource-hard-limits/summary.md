---
task: resource-hard-limits
date: 2026-07-24
rounds: 6
verdict: pass
---

# 任务小结:资源硬上限与膨胀治理(部署层 + server + agent)

长运行部署曾因容器日志与应用产出文件无界增长把宿主机拖死(生产证据:Redis
卷 2.11GB)。本任务给每个增长面加可配置硬上限 + 安全默认值,过期由后台自动
执行,不依赖手动运维。零 Alembic 迁移、零协议破坏性变更、全部新配置有默认值
(回滚 = 回退镜像 + compose)。

## 改动

分三层 + 文档回写,约 43 个源码/配置/文档文件 + 2 个新测试文件。

| 文件 | 摘要 |
|---|---|
| deploy/docker/docker-compose{,.server,.agent}.yml | **Phase A**:每个 service 加 json-file 日志轮转(`max-size 10m`/`max-file 3`);redis 加 `--maxmemory 512mb --maxmemory-policy noeviction` + AOF 自动重写阈值 |
| apps/server/dopilot_server/config/{settings,loader}.py | 新增 `[maintenance]` 段、`[logs].max_file_bytes`、`[artifacts].max_upload_bytes/max_total_bytes`;`stream_maxlen_logs` 默认 1M→100k;`retention_days` 14→30;全字段 env 覆盖 |
| apps/server/dopilot_server/logs/files.py、services/logs.py、models/execution.py | **B1**:单执行日志 100MiB 上限(`append_increment_capped`),超限继续消费/ACK、写截断标记、`log_integrity=truncated`(新增粘滞值) |
| apps/server/dopilot_server/services/maintenance.py、retention.py、redis/{client,reconcile}.py、app.py、api/v1/maintenance.py | **B2/B3/B4**:`RetentionSweepLoop`(常驻);失败安全两阶段清理(标 expired 提交→unlink→删行,失败留 expired 下 tick 重试);event_audit 分批删;`XTRIM MINID` 实装 `log_retention_seconds`;finalize 写 `retained_until` |
| apps/server/dopilot_server/artifacts/{upload,scrapy_store,wheel_store}.py、services/artifacts.py、api/v1/artifacts.py | **B5**:上传分块流式化(413)+ 聚合配额(507)+ 按 sha 引用计数 `publish_lock` 串行化 + 发布/DB 失败回滚(仅回滚本次新建,既有件不误删) |
| apps/server/dopilot_server/logs/sse.py | **B6**:SSE 订阅队列有界(maxsize),满则清空 + CLOSE + 退订 |
| apps/agent/dopilot_agent/config/{settings,loader}.py | **C7**:`[agent]` janitor/TTL/job.log/cache 字段、`[redis]` maxlen/outbox 上限、`[scrapyd]` jobs/finished_to_keep;全字段 env 覆盖 |
| apps/agent/dopilot_agent/janitor.py、runners/python_wheel.py、redis/{commands,logs,events}.py、scrapyd/process.py、artifacts/{cache,wheel_cache}.py、deps.py、main.py | **C1–C6**:`AgentJanitor`(TTL GC 三重安全判定 + 缓存 LRU 持锁淘汰);job.log PIPE/drain 上限;`job.pgid` sidecar;`.logpos` 泄漏修复;引用计数键锁;outbox drop-oldest;scrapyd 保留显式化;内存簿记两档生命周期释放 |
| configs/{server.example,server.docker,agent.example}.toml | 同步全部新配置项 |
| docs/architecture/{03,04,05}.md、docs/decisions/0019-*.md、README | 回写 truncated/自动清理/配置面/部署上限/生产收缩 runbook + 新决策 0019 |
| apps/{server,agent}/tests/test_resource_limits.py(新) | 35 个用例覆盖 plan 全部 TC-01..18(含各故障注入、并发、竞态) |

## 评审历程

Plan 评审 4 轮(前 3 fail→修订,round-04 pass);代码评审 6 轮。

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | 证据契约缺命令/退出码;maintenance unlink 失败留孤儿;janitor 未纳入 consumer 在途集/未持锁 |
| 02 | fail | 测试覆盖不足(虚报);janitor 锁映射仍竞态;缓存淘汰未取锁;artifact 发布失败留未计配额正文 |
| 03 | fail | 测试覆盖仍不足;manifest 发布失败留孤儿;同-sha 并发回滚误删已提交件 |
| 04 | fail | TC-03/06/07/18 覆盖缺口;既有 sha 重复上传 manifest 失败误删既有件 |
| 05 | fail | TC-14 证据未逐个 service 断言日志上限 |
| 06 | **pass** | 无 |

修复要点累积:失败安全清理只删已 unlink 成功的行;引用计数键锁(consumer +
publish);缓存淘汰持 `O_CREAT\|O_EXCL` 锁;save_from_path 按新建/既有归属
回滚;确定性 barrier 并发测试消除 flake;TC-14 逐 service JSON 断言。

## 遗留 minor 及处置

round-06 评审无任何 minor/major/blocker;无遗留项。

（备注:全量套件存在一个与本任务无关的偶发 flake
`test_python_wheel.py::test_wheel_started_orphan_recovered_as_lost`——真实子进程
`killpg` 后的时序断言;隔离与重跑均通过。可另开任务加 wait 循环,不属本任务。)
