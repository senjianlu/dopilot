# Plan 评审:第 10 轮

## 问题清单
- [plan-blocker] R-01 LogsDirGauge 未将物理截断/删除与计数扣减置于同一临界区，仍可能低估目录大小并突破硬预算。
  - 详情:定位：plan.md:67-68、145-148，以及 TC-11b。方案只规定 `calibrate()`、`sub(n)` 各自在同一把锁内，却未规定物理 truncate/unlink 与对应 `sub` 共同持锁。可发生：文件先从 6000B 截到 5000B；校准随后扫描到 5000B 并重置 gauge；维护再执行 `sub(1000)`，得到 4000B，实际仍为 5000B，后续准入即可把目录写过预算。应让截断/删除、实际释放量计算和 gauge 更新在 `gauge.writer()` 的同一临界区内完成，或采用不会重复扣减的校准协议；补充 barrier 用例覆盖“物理修改已完成、sub 尚未执行时校准介入”的交错。
- [plan-blocker] R-02 恢复 runbook 使用了现有 API 不支持的多状态查询，关键停机前置检查实际会返回 400。
  - 详情:定位：plan.md:72 的 `GET /api/v1/tasks?status=queued,running,finalizing`。现有 `apps/server/dopilot_server/api/v1/tasks.py:91-117` 只接受一个必须精确属于 `TASK_STATUSES` 的字符串，逗号连接值会被判为 `task.invalid_status`。该检查直接保护后续删除 Redis volume 的破坏性步骤，不能作为文档细节略过。应改成三个带管理员鉴权的查询并正确处理分页/总数，或把多状态过滤列入 API 改动；同时增加自动化 runbook/API 验证，当前 TC-31 只验证 Compose 配置，无法发现此错误。
- [major] R-03 测试没有验证 `.pth` 随构建产物安装后会自动激活，日志硬界的生产接线可失效而全部用例仍通过。
  - 详情:定位：plan.md:80、TC-01d～TC-01g。TC-01e 在子进程脚本中显式 `import dopilot_agent.logcap`，这绕过了生产依赖的 `.pth` 自动导入；TC-01f 只静态读取 pyproject 和 `.pth` 内容，也不能证明 Hatch 构建结果包含该文件、pip 将其安装到会被 Python 启动处理的位置。应增加 A 档黑盒用例：实际构建 agent wheel、安装到临时隔离环境，再运行一个完全不显式导入 `logcap` 的 crawler 形态子进程并验证文件上限与 SIGTERM；最好同时覆盖 Scrapyd 注入的真实 argv/LOG_FILE 形态。

## 总评
方案的证据表已逐条声明 A 档与文本证据形态，C 档为 0，证据契约合规；多数状态、并发和异常路径也已有细致覆盖。但目录硬预算的同步协议仍不成立，恢复 runbook 含不可执行的安全检查，且核心 `.pth` 生产接线未被真实测试，因此本轮必须 fail。

VERDICT: fail
