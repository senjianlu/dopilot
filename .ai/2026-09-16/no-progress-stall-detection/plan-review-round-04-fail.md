# Plan 评审:第 04 轮

## 问题清单
- [major] R-01 停止期间重投的 run 命令仍能绕过状态机，上报 reclaim 自己制造的 canceled 并覆盖 lost。
  - 详情:定位：plan.md §4.2–4.4、TC-24，以及 apps/agent/dopilot_agent/redis/commands.py:672、redis/events.py:351。方案在 reclaim 等待退出期间保留 phase=started；此时若 run 命令重投，_handle_run 会调用 republish_current，后者直接根据 runner.status 上报终态。TERM 已成功且 job 已退出、但下一次 watchdog 尚未收尾时，真实 ScrapyRunner 返回 canceled，该事件会将 server 的 lost 覆盖为 canceled，违反方案“不 emit 任何事件、保持 lost”的约束。现有即时收尾不会留下这个跨 tick 窗口。请将 republish_current 纳入停止状态机的意图约束，确保停止期间的终态由统一收尾入口处理；补充 A 档测试：reclaim→TERM 成功→job 退出→watchdog 收尾前重投 run，断言不发送 canceled、server 保持 lost，且延期清理仍正常完成。现有 TC-24 未覆盖命令重投入口。

## 总评
方案的 rawf 闸门、轮次声明与证据契约合规，35 条用例均声明 A 档并包含异常路径。但新增跨 tick 停止窗口与既有 run 重投上报路径存在正确性冲突，需补齐意图约束及对应测试后重评。

VERDICT: fail
