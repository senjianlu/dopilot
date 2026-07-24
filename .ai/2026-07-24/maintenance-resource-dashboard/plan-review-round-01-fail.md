# Plan 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 端点的按需采样路径违反“昂贵目录遍历绝不逐请求执行”的既定架构约束
  - 详情:定位：实现方案第 2、3 节及 `stats_interval_seconds=0` 语义。方案规定 loop 关闭、尚未首次 tick 或 ASGITransport 场景下，由 `GET /maintenance/resource-stats` 直接调用 `collect_snapshot`；该函数会遍历 server logs 和 artifacts 目录。此前审计底稿 D2 明确要求快照只从内存提供，昂贵 walk 不得进入请求路径。该设计还会在启动窗口或并发请求时产生重复全目录扫描。应改为端点始终只读缓存；启动时先采样、触发受互斥保护的后台刷新，或在无快照时返回明确的 unavailable/503。若允许 interval=0，也必须定义不执行请求内遍历的行为，并补相应测试。
- [major] R-02 Agent 指标缺少可传递到响应和等级计算的陈旧/离线语义，会把历史样本展示为实时且正常
  - 详情:定位：实现方案第 2 节 agents 采集、第 3 节响应结构及 TC-04/TC-11。Agent 磁盘样本仅随 janitor 每 600 秒更新，节点离线后 `nodes.health["disk"]` 仍会长期保留；方案虽读取样本 `sampled_at` 和节点 `last_seen_at`，但扁平响应条目只有 key/scope/kind/value/limit/level，全局 `sampled_at` 又只是 server 快照时间。因而前端无法区分新鲜样本、陈旧样本和离线节点，旧值仍可能被标为 ok，违背实时资源仪表盘的正确性。应在 API 契约中加入 agent 样本时间/节点最后心跳时间及明确的 stale/unavailable 判定，并增加过期样本、离线节点和缺失 disk 样本的自动化用例。
- [major] R-03 API 的 level 契约与 Web 设计及测试相互矛盾
  - 详情:定位：目标和第 2、3 节将 level 定义为 `ok|warn|critical`，板块故障另由顶层 `unavailable` 列表表达；第 4 节和 TC-12 却要求条目支持 `unavailable→gray`。这会导致响应 schema、前端 TypeScript 类型和测试载荷无法同时忠于方案，且部分字段缺失与整个 scope 故障的表现不明确。应统一契约：要么把 `unavailable` 纳入条目 level 并规定 value/limit 的 nullable 规则，要么仅使用顶层 unavailable/stale 状态并让前端据此渲染；随后修正 TC-03、TC-04、TC-12，覆盖整板块和单指标不可用两种路径。

## 总评
方案的证据契约合规：所有 16 条用例均逐条声明档位与证据形态，C 档为 0，且包含多条异常与边界路径。但请求内昂贵采样直接违反既定 D2 架构约束，Agent 陈旧状态和 unavailable 契约也尚未闭合，因此本轮必须 fail 并修订方案后重评。

VERDICT: fail
