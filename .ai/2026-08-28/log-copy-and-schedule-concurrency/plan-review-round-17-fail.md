# Plan 评审:第 17 轮

## 问题清单
- [major] R-01 测试未证明定时触发与手动触发真正共用同一并发额度池
  - 详情:定位：B2“不区分 source”口径及 TC-04、TC-10。TC-04 只验证连续 trigger-now 自身受限；TC-10 虽为 timer 超限，但前置条件没有声明已有 active task 的 source。因此，将 schedule_timer 与 schedule_trigger_now 分成两个独立额度池的错误实现仍可能通过全部用例。请增加 A 档交叉来源用例，至少明确验证已有 schedule_timer active task 时 trigger-now 返回 409，以及已有 schedule_trigger_now active task 时 fire_timer 跳过且不创建任务，并声明完整命令、stdout/stderr 和退出码证据。

## 总评
方案的行锁串行化、迁移路径、输入边界及 rawf 证据契约总体自洽，28 条用例均声明档位和证据形态，C 档为 0。当前缺口涉及并发口径的核心验收标准，错误的分池实现仍可获得全绿证据，因此按 plan-review 规则判定 fail。

VERDICT: fail
