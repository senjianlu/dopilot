# 0012:领域模型：BuildArtifact → ExecutionTemplate → Schedule → Task → Execution

- 日期:阶段 1.8（2026-06 下旬）；阶段 2.2 补注
- 背景:阶段 1 的口径偏 Scrapy（"爬虫 / 任务模板 / execution-attempt"），
  接入 Python 脚本与 Docker 前需要一次跨执行类型的概念与 API clean-cut。
- 决定:产品与 public API 统一使用五级模型：

  ```text
  构建产物 BuildArtifact → 执行模板 ExecutionTemplate → 定时调度 Schedule
    → 任务 Task → 执行实例 Execution
  ```

  - **BuildArtifact** 是"可执行产物"（非构建过程）真实 DB 实体；
    `artifact_type` 取 `scrapy`（`.egg`）/ `python_wheel`（`.whl`）/
    `docker_image`（预留）。
  - **ExecutionTemplate** 必须绑定一个构建产物，保存默认执行参数、节点
    策略与节点选择；Scrapy 执行命令只读展示。
  - **Schedule** 必须引用一个执行模板，可覆盖执行参数/节点策略/节点，
    **不可覆盖构建产物**。
  - **Task** 是一次触发的父级运行记录（直接运行产物、运行模板、
    trigger-now、timer firing 都会创建）；创建时冻结 resolved snapshot，
    优先级 `schedule override > template default > artifact default`。
  - **Execution** 是任务按节点 fan-out 后的单节点原子执行单元。
  - 节点选择在健康/未下线/未删除之外，还按 artifact 类型过滤节点能力
    （`scrapy → scrapy`、`python_wheel → python_wheel`、
    `docker_image → docker_runtime`）。
- 影响:
  - **wire/disk/agent 边界保留旧字段名**（兼容 seam）：`execution_id` 表示
    父级 Task id、`attempt_id` 表示原子 Execution id；这些名字只允许存在于
    Redis/磁盘/agent 边界，核心域使用新口径。`task_type` 仅作为 agent wire
    字段保留在边界。
  - 阶段 2.2 补注:`execution_templates.name` 与 `schedules.name` 唯一
    （冲突 409）；`schedules` 行级 `enabled`（默认 `false`）控制该定时是否
    被调度器注册——`enabled=false` 仍可列出/查看/更新/删除并可
    `trigger-now` 手动运行。行级 `schedules.enabled` 与全局
    `[scheduler].enabled`（决定 in-process runner 是否存在）是两个开关。
