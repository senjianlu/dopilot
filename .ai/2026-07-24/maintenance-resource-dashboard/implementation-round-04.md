---
task: maintenance-resource-dashboard
round: 04
date: 2026-07-24
---

# 实现记录:第 04 轮(修复轮)

修复 review-round-03-fail 的 1 blocker(R-01 TC-12 覆盖)+ 1 major(R-02
采集降级语义真实缺陷)。修复轮上限经用户授权由默认 3 放宽至 6
(plan.md frontmatter `impl_fix_max_rounds: 6`)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| .ai/.../plan.md | frontmatter 写入 `impl_fix_max_rounds: 6` + 授权来源注释 |
| apps/server/dopilot_server/resource_stats.py | **R-02 源码修复**:`_du` 返回 `int\|None`——目录不存在→0(新部署合法空),存在但 `os.walk` onerror / `os.stat` 失败→`None`(访问故障,渲染为 unknown 而非伪装 0);`_read_nodes` 改返回 `(nodes, ok)`,DB 失败→`ok=False`;`collect_snapshot` 在 `ok=False` 时追加显式 `agents` unavailable scope,不再静默丢弃全部 agent |
| apps/server/tests/test_resource_stats.py | R-02 用例:`_du` 缺失→0 / 访问失败→None、server scope 单目录失败→该条 unknown 且 scope 仍 ok、nodes 读失败→`agents` unavailable 且 server 照常、`_read_nodes` 失败返回 `([],False)` |
| apps/web/app/(app)/maintenance/page.tsx | ScopeCard 的 stale 样本时间 / unavailable last_seen 描述加 testid(`resource-scope-sampled-*` / `resource-scope-lastseen-*`) |
| apps/web/app/(app)/maintenance/__tests__/maintenance.test.tsx | **R-01 TC-12 补齐**:fixture 加 ok/unknown 两级条目;断言四级 tone(ok→green、warn→amber、critical→red、unknown→gray)、stale 样本时间与 unavailable last_seen 呈现、AOF 取消不调用、终态清理确认执行(dry_run:false)与取消不调用、dry-run 断言 dry_run:true |
| evidence/tc01-11-server-resource-stats.txt、tc12-14-web.txt、tc15-pytest.txt、tc15-ruff.txt、tc15-web-test.txt | 重生成 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | plan TC-12 要求的断言补齐:①四级 level→data-tone 全覆盖(新增 ok→green、unknown→gray,fixture 增 `server.logs_bytes`(ok/null-limit)与 `server.max_log_file_bytes`(unknown));②操作补 AOF 取消、terminal-cleanup 确认执行(断言 `dry_run:false`)与取消、dry-run 断言 `dry_run:true`;③stale 样本时间(`resource-scope-sampled-agent:a1`)与 unavailable 的 `last_seen_at`(`resource-scope-lastseen-agent:a2`)经新增 testid 断言呈现。`tc12-14-web.txt` 现 `18 passed`(maintenance 10 + format 8),含真实命令 + 输出 + 退出码。 |
| R-02 | major | 采集失败不再伪装成零值/省略:(a)`_du` 用 `os.path.exists` + `os.walk(onerror=...)` 区分"真空目录(0,ok)"与"存在但不可读(None→unknown)",misconfig/权限故障不再显示为"无用量";(b)`_read_nodes` 返回 `ok` 标志,DB 读失败时 `collect_snapshot` 追加显式 `agents` unavailable scope,而非静默丢弃全部 agent 使 DB 故障看似"无 agent"。单目录失败仍只降级该条(unknown),不拖垮 server scope;契约"板块失败仅降级对应板块"得以满足。5 个新增 A 档用例覆盖。 |

## 测试结果

全量 `623 passed, 1 skipped`(TC-17 无 env 跳过,真 PG 由 tc17 脚本 pass);
web `88 passed`;ruff/lint/tsc clean。仅列本轮受影响用例。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-11-server-resource-stats.txt(含 `_du` 区分 missing/访问失败、server scope 单目录失败 unknown) |
| TC-03 | A | pass | tc01-11-server-resource-stats.txt(新增 `_du`×2、nodes 读失败→agents unavailable、`_read_nodes` ok 标志;既有 redis/PG 隔离) |
| TC-04 | A | pass | tc01-11-server-resource-stats.txt(既有六节点/畸形/401/无快照零采样/enabled=false) |
| TC-12 | A | pass | tc12-14-web.txt(四级 tone、stale/unavailable 时间、三操作确认+取消、dry-run/execute) |
| TC-13/14 | A | pass | tc12-14-web.txt(轮询清理、formatBytes GB/TB) |
| TC-15 | A | pass | tc15-pytest.txt(`623 passed`)、tc15-ruff.txt(clean)、tc15-web-test.txt(`88 passed`)、tc15-web-lint/tsc(沿用 round-01,web 配置未变;本轮 tsc/lint 复跑亦 clean) |
| TC-17 | A | pass | tc17-postgres.txt(源码/脚本未变,`# Script exit code: 0`) |
| TC-02,05..11,16 | A/B | pass | 沿用前轮证据(相应源码未变;server/agent 全量已含其绿) |

## 与方案的偏差

- 无新增偏差(round-01 的 `DiskStatus` 独立模块、Progress 中性填充仍适用)。
- `_du` 语义细化(missing=0 / 访问失败=None)是对 plan"目录字节"采集的健壮化,
  与 plan 意图一致,不改采集面与配置面。
