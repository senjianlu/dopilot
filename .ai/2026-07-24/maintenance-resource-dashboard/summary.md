---
task: maintenance-resource-dashboard
date: 2026-07-24
rounds: 7
verdict: pass
---

# 任务小结:运维清理页面重写为实时资源仪表盘(含安全操作三件套)

上一任务(resource-hard-limits, a19985d)给所有无界增长面加了硬上限,但运维者
看不到"当前值 vs 临界值"。本任务把 `/maintenance` 重写为资源仪表盘:server
磁盘 / PostgreSQL / Redis / 每 agent 磁盘的当前用量与上限、ok/warn/critical
分级,约 10s 轮询;并提供三个安全操作(立即保留清扫 / 终态清理 dry-run+确认 /
Redis BGREWRITEAOF)。零 Alembic 迁移、零协议破坏(心跳 `detail["disk"]` 走
自由字段)、采样只在后台 loop、端点只读内存快照绝不逐请求遍历。

## 改动

约 30 个源码/配置/文档文件 + 4 个测试文件。

| 文件 | 摘要 |
|---|---|
| apps/server/dopilot_server/resource_stats.py(新) | `collect_snapshot`(逐板块各开各的 session 事务隔离、失败仅降级该 scope;server 目录字节/最大单日志文件、PG 五表行数+`to_regclass` 参数化字节+`pg_database_size`+最老终态任务/event_audit 年龄且谓词与清扫同源、Redis INFO+XINFO 流长度/首条目年龄且命令流仅长度、agent 动态状态+防御性解析)、`_level`(占比 70/90 + 年龄互斥分段)、`ResourceStatsLoop` |
| apps/server/dopilot_server/api/v1/maintenance.py | `GET /maintenance/resource-stats`(只读缓存、无快照返回真实 sweep_enabled、零请求路径采样)、`POST /maintenance/sweep-now`(步骤级故障隔离 + retention 0 skip + 逐流 trim 结果)、`POST /maintenance/redis-rewrite-aof`(无 redis/异常 503) |
| apps/server/dopilot_server/api/v1/schemas.py | `ResourceStats*`、`SweepStep/Now`、`RewriteAof` 响应模型 |
| apps/server/dopilot_server/redis/client.py | `info`/`xinfo_stream`(no-such-key→空流映射)/`bgrewriteaof` |
| apps/server/dopilot_server/services/maintenance.py | `trim_log_streams` 结构化逐流返回(失败可见,不再静默) |
| apps/server/dopilot_server/retention.py | `retention_days=0` 短路(0=关闭,而非 cutoff=now 立删全部) |
| apps/server/dopilot_server/app.py、config/{settings,loader}.py | wire `ResourceStatsLoop`;`[maintenance].stats_interval_seconds`(默认 60,env 覆盖) |
| apps/agent/dopilot_agent/disk_status.py(新)、deps.py、janitor.py、redis/heartbeat.py、main.py | `DiskStatus` 共享采样对象;janitor 每轮 `asyncio.to_thread` 采集固定形状磁盘样本(严格访问失败语义:不可读→null,不伪装 0)经心跳 `detail["disk"]` 上报;heartbeat 只读缓存零遍历 |
| apps/web/app/(app)/maintenance/page.tsx | 整页重写:scope 卡 + 指标行 + Progress + level ToneBadge + scope 状态(stale/unavailable)+ 首采骨架;10s 轮询;三操作各带 useConfirm;VACUUM/容器日志文案 |
| apps/web/lib/{api/maintenance,api/types,format}.ts、components/ui/progress.tsx、i18n/locales/{en,zh}.ts | API/类型、formatBytes GB/TB、shadcn Progress、`maintenance.*` 键块重构 |
| configs/server.{example,docker}.toml、docs/architecture/{04,06}.md | 配置样例 + 配置面/资源仪表盘章节/页面双职责回写 |
| apps/server/tests/test_resource_stats.py(新)、apps/agent/tests/{test_resource_limits,test_heartbeat_worker}.py、apps/web/.../maintenance.test.tsx(新)、apps/web/lib/__tests__/format.test.ts | TC-01..17 全覆盖 |

## 评审历程

Plan 评审 11 轮(前 10 fail→修订,round-11 pass;轮次上限经用户两次授权
放宽至 12)。代码评审 7 轮(轮次上限经用户三次授权 3→6→10)。

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | TC-10 证据被 `-k` 误 deselect;TC-05 prune 分支/TC-07 lifespan/TC-08 TOML 缺;TC-17 缺外层命令+退出码 |
| 02 | fail | TC-10 证据仍占位命令且缺零遍历断言;无快照响应写死 sweep_enabled=True(真实缺陷) |
| 03 | fail | TC-12 页面断言不全;采集降级语义:`_du`/nodes 读失败伪装零值/丢 agent(真实缺陷) |
| 04 | fail | agent 侧同类:`_tree_size`/count helper 吞 OSError→假 0,TC-09 未覆盖真实遍历失败 |
| 05 | fail | count helper 用 `exists()`/`glob()` 仍遮蔽访问失败;缓存淘汰后样本报旧总量(真实缺陷) |
| 06 | fail | `_count_dirs.is_dir()` 仍吞 PermissionError;server `_du` 用 `exists()` 遮蔽 |
| 07 | **pass** | 无 |

修复要点累积:无快照如实报 sweep_enabled;retention_days=0 统一为"关闭";
trim 失败结构化可见;server/agent 全部 size/count helper 统一"仅
FileNotFoundError→0,PermissionError 传播→null/unknown";nodes 读失败显式
`agents` unavailable;缓存样本严格测量且反映淘汰后真实树。

## 遗留 minor 及处置

round-07 评审问题清单为空,无任何 minor/major/blocker;无遗留项。
