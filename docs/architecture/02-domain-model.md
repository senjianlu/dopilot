# 领域模型

> 决策依据:[0012 领域模型 clean-cut](../decisions/0012-domain-model-clean-cut.md)、
> [0014 节点策略与推模式](../decisions/0014-node-strategy-and-push-mode.md)。

## 五级模型

```text
构建产物 BuildArtifact
  -> 执行模板 ExecutionTemplate
    -> 定时调度 Schedule
      -> 任务 Task
        -> 执行实例 Execution
```

| 实体 | 要点 |
|---|---|
| **BuildArtifact** | 可执行产物（非构建过程）。`artifact_type`:`scrapy`（`.egg`）/ `python_wheel`（`.whl`）均可运行;`docker_image` 预留未实现。支持归档（`archived_at`）。 |
| **ExecutionTemplate** | 必须绑定一个构建产物;保存默认执行参数、节点策略与节点选择。Scrapy 执行命令只读展示。`name` 唯一（冲突 409）。 |
| **Schedule** | 必须引用一个执行模板;可覆盖执行参数/节点策略/节点，**不可覆盖构建产物**。行级 `enabled`（默认 `false`）控制是否被调度器注册;`enabled=false` 仍可 CRUD 与 `trigger-now`。触发器为 interval（`interval_seconds`）或 5 段 crontab（`cron`）。 |
| **Task** | 一次触发的父级运行记录（直接运行产物 / 运行模板 / trigger-now / timer firing 均创建）。创建时冻结 resolved snapshot，优先级 `schedule override > template default > artifact default`。 |
| **Execution** | 任务按节点 fan-out 后的单节点原子执行单元;经任务快照可追溯到构建产物。 |

## 节点选择

触发时动态归约:`node_strategy` 三态 `selected` / `all`（默认，并发
fan-out）/ `random`（健康节点中随机一个）。过滤条件 = 健康（heartbeat）
∧ 未下线/未删除 ∧ 能力匹配:

```text
scrapy -> scrapy    python_wheel -> python_wheel    docker_image -> docker_runtime
```

推模式 = 绕过定时、主动下发到指定 worker 立即执行，经统一的
`BaseExecutor`（`apps/server/dopilot_server/executors/`）按 resolved
`artifact_type` 多态分派。

## 命名兼容 seam

Redis/磁盘/agent 边界保留旧字段名:`execution_id` = 父级 **Task** id、
`attempt_id` = 原子 **Execution** id、`task_type` = agent wire 上的
artifact 类型。这些名字**只允许存在于 wire/disk/agent 边界**;public
API、Web 与核心域一律使用 Task/Execution 口径。
