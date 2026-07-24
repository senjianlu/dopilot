# 0002:三类被调度对象按 Scrapy → Python 脚本 → Docker 严格分期

- 日期:2026-06-17
- 背景:dopilot 需要支持三类被调度对象——① Scrapy 框架爬虫（经 scrapyd）、
  ② Docker 容器内长连接爬虫、③ 一次性 Python 脚本。三类的执行模型差异大，
  一起做会把执行器抽象做糊。
- 决定:严格按 **① Scrapy（经 scrapyd）→ ③ Python 脚本 → ② Docker 长连接**
  的顺序分期实现，一类做稳再上下一类。为避免"三类执行器各改三遍"，先立三条
  抽象缝：`BaseExecutor`（server 侧按 `artifact_type` 多态分派）、`LogSource`
  （统一日志来源）、`node_strategy`（节点选择三态）。
- 影响:
  - 当前状态:Scrapy `.egg` 与 Python `.whl` 均已实现可运行；**Docker 长连接
    爬虫仍是未实现的未来阶段**。
  - Docker 阶段的"定时语义"（起新容器 vs 对常驻容器发指令）在其开工前须先
    定义（历史开放问题，尚未裁决）。
  - artifact 类型 → 节点能力过滤映射：`scrapy → scrapy`、
    `python_wheel → python_wheel`、`docker_image → docker_runtime`。
