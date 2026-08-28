# Plan 评审:第 10 轮

## 问题清单
- [major] R-01 TC-37/TC-38 要求从返回 None 的 fire_timer 读取 skip_reason，测试契约不可执行
  - 详情:定位：plan.md:347-351、376-384、599、605。方案规定 acquire_firing_slot 返回 FiringSlot，而 fire_timer 消费该结果并在跳过时返回 None；但 TC-37/TC-38 又要求直接调用 fire_timer 后同时断言返回 None 和 skip_reason。实现者无法按表中步骤取得该字段，且第 4 步还同时写了“返回 None”和“返回 SKIP_BACKLOG”。请统一契约：acquire_firing_slot 的所有跳过分支均返回 FiringSlot；fire_timer 若保持既有 None 返回值，则测试通过 spy 捕获内部 FiringSlot，或另行直接测试 acquire_firing_slot，不能从 None 读取原因。
- [major] R-02 所谓多分块用例实际只读取一个 256KiB 块，未覆盖流式拼接边界
  - 详情:定位：plan.md:232-253、574。aiter_snapshot 的默认 chunk_size 是 262144 字节，但 TC-06 只创建 200KB 文件，并错误声称会跨多个 64KiB chunk；其余快照用例也仅使用 100KB 文件。因此第二块及后续块的 offset/remaining 逻辑即使存在遗漏、重叠或提前停止，全部测试仍可通过。请把文件扩大到至少两个默认块以上，或在该用例显式传 chunk_size=65536，并断言确实产生多个块后再校验拼接内容和长度。
- [major] R-03 后端没有用例证明 execution_id 会选择指定 execution 的日志
  - 详情:定位：plan.md:124-140、569-577、592、603。TC-24/TC-35 只证明前端组件和 helper 会发送 execution_id；后端下载用例均只描述单个 execution，未构造两个 execution 并请求非默认项。下载路由即使忽略 execution_id、始终调用默认 primary execution，现有测试仍会全绿，扇出到多节点的任务会下载错误日志。请增加 A 档后端用例：同一 task 创建至少两个内容不同的 execution 日志，显式请求非 primary 的 execution_id，并断言响应体及文件名对应所选 execution；可同时覆盖不属于该 task 的 execution_id 返回 404。

## 总评
证据档位声明和 C 档比例符合工作流约定，调度行锁及下载资源生命周期设计整体已较完整。但当前存在一项不可执行的测试契约，以及多分块读取和多 execution 下载两个关键验收缺口，按 plan-review 规则应 fail。

VERDICT: fail
