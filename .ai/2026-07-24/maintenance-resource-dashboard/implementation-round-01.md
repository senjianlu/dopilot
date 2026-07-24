---
task: maintenance-resource-dashboard
round: 01
date: 2026-07-24
---

# 实现记录:第 01 轮

## 本轮改动

按 approved plan 实现,分 server / agent / web / docs 四层 + 测试。

| 文件 | 改动摘要 |
|---|---|
| apps/server/dopilot_server/config/settings.py | `MaintenanceSettings` 新增 `stats_interval_seconds: int = 60`(0 = 关闭采样 loop) |
| apps/server/dopilot_server/config/loader.py | 新增 env 覆盖 `DOPILOT_MAINTENANCE_STATS_INTERVAL_SECONDS` |
| apps/server/dopilot_server/redis/client.py | `RedisStreamClient` 协议 + `RedisStreams` 新增 `info(section)`、`xinfo_stream(stream)`(`no such key`→空流映射,其他 ResponseError 抛出)、`bgrewriteaof()` |
| apps/server/dopilot_server/services/maintenance.py | `trim_log_streams` 改结构化逐流返回 `{stream:{"trimmed":n}\|{"error":msg}}`(自动 loop 兼容,仅记日志) |
| apps/server/dopilot_server/retention.py | `sweep_once`:`retention_days=0` 短路跳过终态清理(0=关闭,而非 cutoff=now 立删) |
| apps/server/dopilot_server/resource_stats.py(新) | `collect_snapshot(sessionmaker,settings,redis)`——逐板块**各开各的 session** 事务隔离;server(目录字节走 `logs.root_dir`/`artifacts.root_dir`、`MAX(size_bytes)`、逐卷 disk_usage 去重)、postgres(五表行数 + PG `to_regclass` 参数化字节 + `pg_database_size(current_database())` + 最老终态任务/event_audit 年龄,谓词 `COALESCE(finished_at,created_at)`/`processed_at` 与清扫同源)、redis(INFO memory/persistence + XINFO 流长度/首条目年龄,命令流仅长度无年龄)、agents(动态 `_aggregate_node_status` + 防御性解析);`_level`(占比 70/90、年龄互斥分段 `critical_at=max(2·limit,limit+grace)`、null-limit→ok、null-value→unknown);`ResourceStatsLoop`(启动即采、异常不死) |
| apps/server/dopilot_server/api/v1/schemas.py | `ResourceStatEntry`/`ResourceStatScope`/`ResourceStatsResponse`、`SweepStepResult`/`SweepNowResponse`、`RewriteAofResponse` |
| apps/server/dopilot_server/api/v1/maintenance.py | `GET /maintenance/resource-stats`(只读缓存、无快照返回空、零请求路径采样)、`POST /maintenance/sweep-now`(步骤级故障隔离 + retention 0 skip + 逐流 trim 结果)、`POST /maintenance/redis-rewrite-aof`(无 redis/调用异常均 503);均 `Depends(get_current_admin)` |
| apps/server/dopilot_server/app.py | lifespan wire `ResourceStatsLoop`(`stats_interval_seconds>0` 时),挂 `app.state.resource_stats`,反向停 |
| apps/agent/dopilot_agent/disk_status.py(新) | `DiskStatus` 线程安全单值容器(见偏差:未放 deps.py) |
| apps/agent/dopilot_agent/deps.py | 建 `DiskStatus`、入 `AgentRuntime`、传 `HeartbeatWorker` |
| apps/agent/dopilot_agent/janitor.py | 构造新增 `disk_status`;`_sweep_cache` 始终记 `_last_cache_bytes`(供采样复用,免二次遍历);`_collect_disk_sample`(在 `asyncio.to_thread`,固定形状小样本,子项 `_guard` 隔离)+ `_count_dirs`/`_count_glob`/`_volume` 辅助 |
| apps/agent/dopilot_agent/redis/heartbeat.py | `build_request` 附 `detail["disk"]`(样本缺失不加 key,读缓存零遍历) |
| apps/agent/dopilot_agent/main.py | janitor 构造传 `runtime.disk_status` |
| apps/web/lib/format.ts | `formatBytes` 扩展 KB/MB/GB/TB |
| apps/web/components/ui/progress.tsx(新) | shadcn Progress(radix-ui umbrella,中性 primary 填充;等级色由 ToneBadge 承载) |
| apps/web/lib/api/maintenance.ts、types.ts | `getResourceStats`/`sweepNow`/`rewriteAof` + 对应类型 |
| apps/web/app/(app)/maintenance/page.tsx | 整页重写:资源仪表盘(scope 卡 + 指标行 + Progress + level ToneBadge + scope 状态)10s `setInterval` 轮询(active 标志清理)+ 首采骨架;操作三件套(sweep/rewrite-aof/cleanup)各带 useConfirm;VACUUM/容器日志文案注 |
| apps/web/lib/i18n/locales/{en,zh}.ts | `maintenance.*` 键块重构(保留 cleanup 键 + 新增 dashboard/metrics/actions/staleness),`errors.redisUnavailable` |
| docs/architecture/04-configuration.md、06-web-frontend.md | 配置项 + 资源仪表盘章节 + 页面双职责 + `retention_days=0=关闭` 说明 |
| configs/server.example.toml、server.docker.toml | 同步 `stats_interval_seconds` |
| apps/server/tests/test_resource_stats.py(新) | TC-01..08、11、17 |
| apps/agent/tests/test_resource_limits.py、test_heartbeat_worker.py | TC-09、10 追加 |
| apps/web/.../maintenance.test.tsx(新)、lib/__tests__/format.test.ts | TC-12、13、14 |

## 修复对照

第 1 轮,无。(plan 评审 11 轮 pass 的意见已在 plan.md 落定,本轮按定稿实现。)

## 测试结果

档位照抄 plan;A 档原始输出在 `evidence/`。全量 `613 passed, 1 skipped`
(跳过项即 TC-17 在无 `DOPILOT_TEST_PG_URL` 时,已由 tc17 脚本用真 PG 补跑
pass);web `85 passed`;ruff/lint/tsc 全 clean。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-11-server-resource-stats.txt(`test_tc01_snapshot_shape_and_configured_roots`:日志/制品字节取自配置根、postgres 行数、字节 null) |
| TC-02 | A | pass | tc01-11-server-resource-stats.txt(`test_tc02_*`:占比 69/70/89/90、年龄 G<W 与 G>W 两组、谓词反例 finished_at/processed_at、旋钮 0 uncapped、enabled=false→sweep_enabled) |
| TC-03 | A | pass | tc01-11-server-resource-stats.txt(`test_tc03_*`:正常/空流两态/`no such key` 映射/整板块 unavailable/AOF 缺失 unknown/命令流无年龄/**PG 故障隔离 server+redis+agents 照常**) |
| TC-04 | A | pass | tc01-11-server-resource-stats.txt(`test_tc04_*`:六类节点 ok/ok/stale/unavailable×3 含断联回归、畸形样本隔离、401/200、**无快照零采样 calls==0**) |
| TC-05 | A | pass | tc01-11-server-resource-stats.txt(`test_tc05_*`:401、全成功、cleanup 失败其余仍跑、单流 XTRIM 失败逐流明细、无 redis skip、retention 0 未删数据) |
| TC-06 | A | pass | tc01-11-server-resource-stats.txt(`test_tc06_*`:401、200+bgrewriteaof 记一次、无 redis 503、调用异常 503) |
| TC-07 | A | pass | tc01-11-server-resource-stats.txt(`test_tc07_*`:loop 首采+异常恢复、RetentionSweepLoop retention 0 不删) |
| TC-08 | A | pass | tc01-11-server-resource-stats.txt(默认 60、env=5 覆盖) |
| TC-09 | A | pass | tc09-10-agent-disk.txt(`test_tc09_*`:各计数/字节匹配已知树、子项故障 volume 置 null 不炸) |
| TC-10 | A | pass | tc09-10-agent-disk.txt(有样本 detail["disk"] 等于缓存且 scrapyd 保留、无样本无 disk key) |
| TC-11 | A | pass | tc01-11-server-resource-stats.txt(心跳 disk → nodes.health → resource-stats agent scope ok) |
| TC-12 | A | pass | tc12-14-web.txt(scope/level tone/null-limit "—"/stale+unavailable/首采骨架/三操作 confirm 接受+取消/cleanup dry-run 摘要) |
| TC-13 | A | pass | tc12-14-web.txt(fake timers advance 10s→第 2 次调用、unmount 后无新调用) |
| TC-14 | A | pass | tc12-14-web.txt(formatBytes GB/TB + 既有 KB/MB 不回归) |
| TC-15 | A | pass | tc15-pytest.txt(`613 passed`)、tc15-ruff.txt(clean)、tc15-web-test.txt(`85 passed`)、tc15-web-lint.txt(clean)、tc15-web-tsc.txt(exit 0) |
| TC-16 | B | pass | tc16-doc-config-refs.txt(全部 `文件:行号`) |
| TC-17 | A | pass | tc17-postgres.sh + tc17-postgres.txt(真 postgres:16 容器 → alembic upgrade head → `test_tc17_...real` PASSED,relation/db size 为非负 int、行数≥1) |

## 与方案的偏差

- **`DiskStatus` 落 `disk_status.py` 而非 `deps.py`**:plan 写"deps.py 新增
  DiskStatus",但 `deps.py` 已 `import HeartbeatWorker`,而 heartbeat 需引用
  `DiskStatus` 类型 → 会形成循环 import。故将 `DiskStatus` 抽到独立小模块
  `dopilot_agent/disk_status.py`,`deps` 与 `redis.heartbeat` 均从此导入。
  职责与接线不变,纯放置位置调整,无功能影响。
- **Progress 组件保持中性 primary 填充**:等级颜色由 `ToneBadge` 承载(遵守
  shadcn skill"className 不覆盖组件颜色"),用量条只表达占比,不再加 level
  色。与 plan"Progress 用量条 + ToneBadge 等级"一致。
- 其余无偏差。
