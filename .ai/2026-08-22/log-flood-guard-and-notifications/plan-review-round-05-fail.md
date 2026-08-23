# Plan 评审:第 05 轮

## 问题清单
- [plan-blocker] R-01 以会被 retention 删除的 Task 行充当连续失败账本，无法保持跨保留窗口的连续计数。
  - 详情:定位：plan.md:102 的“从账本重算”设计，以及现有 retention/cleanup_terminal_data 会按 logs.retention_days 删除 Task、Execution 和日志行。调度间隔较长时，连续失败的较早 Task 会先被清理；之后的失败只能从剩余行重算，永远达不到连续阈值。方案须定义独立且保留期适配的结果账本/检查点，或在清理时原子保留必要的连续状态；补充“无成功间隔、旧结果已清理、下一次失败仍正确自动禁用”的自动化用例。
- [major] R-02 Scrapyd 日志防护仍是轮询后的截回，未能兑现所声明的 agent 本地磁盘硬界。
  - 详情:定位：plan.md:79、132-136 与 TC-01b。作业在两次 reconcile 之间可任意高速持续写入；当前 CommandConsumer 还会进行最长 command_block_ms 的阻塞读取。方案只在下一 tick 后 truncate，未限制该窗口内的写入量，因此不能保证 32MiB（或任何受控上界），极端洪泛仍可先耗尽磁盘。须在方案中采用写入边界可强制执行的机制（如每执行独立的文件系统配额/受控日志 sink），或明确可证明的最大写入量与安全余量；测试也应覆盖 watchdog 盲窗中的持续高速写入，而非只在每次 tick 后检查文件大小。
- [major] R-03 启动即清理这一验收行为没有端到端启动接线与顺序测试。
  - 详情:定位：plan.md:70、186-189；TC-12、TC-13~17 仅直接调用 StreamGuard、maintenance 或 janitor 的单次方法。它们不能证明 server lifespan 会在启动消费者前 await StreamGuard/Gauge 校准，也不能证明 agent runtime 实际启动 C8 janitor sweep。若接线遗漏或顺序回归，全部现有 TC 仍可通过而 G1 失效。应增加 server lifespan 与 agent run_agent 的自动化测试，断言相应清理被启动并满足“先清理/校准、后消费者”的顺序。

## 总评
测试用例逐条声明 A 档和完整原始输出证据形态，C 档为 0，证据契约合规；多数异常路径也已有覆盖。但结果账本与既有保留清理不自洽，且本地磁盘和启动清理验收仍存在关键缺口，方案需修订后重评。

VERDICT: fail
