# Plan 评审:第 09 轮

## 问题清单
- [major] R-01 Agent 磁盘样本缺少不可信输入校验与异常用例，单个畸形心跳可能破坏 agents 板块采集
  - 详情:定位：§2 `agents` 采集与 TC-04/TC-11。`AgentHeartbeatRequest.detail` 明确是自由 `dict[str, Any]`，数据库中也可能保留旧版本、人工写入或畸形的 `health["disk"]`；方案却直接使用 `sampled_at`、`interval_seconds`、嵌套 bytes/count/limit 计算时间与等级，未定义类型、范围和时间格式校验，也未说明按单个 agent 隔离解析失败。TC-04/TC-11 只覆盖合法样本，因此无法证明畸形日期、非数值/负数 interval、缺失或错误类型的嵌套字段不会令整个 agents 采集失败，甚至导致本轮快照无法更新。应在方案中规定服务端对自由 dict 做防御性解析，并将错误限制在对应 agent scope（`unavailable` 或条目 `unknown`）；同时增加包含畸形时间、错误类型、零/负 interval 和部分字段缺失的 A 档测试，断言其他 agent 及其他 scope 仍正常。

## 总评
方案整体与 rawf 的 plan-review 闸、证据档位契约和既有异步架构基本一致，17 条用例也都逐条声明了档位与证据形态，C 档为零。当前主要缺口位于自由协议字段的信任边界：在补充防御性解析及相应异常测试前，测试尚未真实覆盖该关键边界路径，因此判定 fail。

VERDICT: fail
