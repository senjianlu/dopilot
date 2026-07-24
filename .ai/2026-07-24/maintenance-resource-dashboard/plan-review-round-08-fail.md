# Plan 评审:第 08 轮

## 问题清单
- [major] R-01 Redis 采集未定义空流语义，正常的新部署可能被误判为整个 Redis 板块不可用
  - 详情:定位：§2 `redis` 采集及 TC-03。方案对 `LOG_STREAM`、`EVENT_STREAM` 和每个 agent 的 command stream 直接调用 `XINFO STREAM`，并规定板块异常时整个 scope 为 `unavailable`；但 Redis 对尚未创建的 stream 返回 `ERR no such key`。新部署、尚无日志/事件或某节点尚无命令时都是正常状态，却会令整个 Redis scope 降级，且 TC-03 只覆盖正常返回和一般异常，未覆盖不存在的流。应在方案中明确由适配器或采集层把 `no such key` 映射为 `length=0、first-entry=null`，其他 Redis 错误仍按故障处理，并增加空 Redis/部分 command stream 不存在的 A 档测试。

## 总评
方案整体结构、rawf 轮次约定和测试证据契约均合规，17 条用例逐条声明了档位与证据形态，且没有 C 档降级。当前存在一个会让正常空环境仪表盘错误降级的 Redis 正确性缺口，补齐空流语义及对应测试后可重评。

VERDICT: fail
