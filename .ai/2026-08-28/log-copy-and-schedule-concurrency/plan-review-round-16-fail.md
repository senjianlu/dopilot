# Plan 评审:第 16 轮

## 问题清单
- [major] R-01 布尔值拒绝测试未覆盖更新路径，PUT 可把 false 静默转换为“不限并发”
  - 详情:plan.md:232-248 要求 ScheduleCreateRequest 与 ScheduleUpdateRequest 都使用 before-validator 拒绝 bool，且 service 两条路径均校验；plan.md:375 还声称 TC-02 覆盖 POST/PUT/service。但 TC-02 只覆盖 POST 和 create_schedule 直调，TC-03 的 PUT 只测整数值域。实现若仅给 Create schema 加 validator，PUT false 会被 Pydantic 转成 0 并关闭并发闸，全部现有用例仍可通过。请在 TC-03 增加 PUT true/false → 422，并增加 update_schedule 直调 bool → 400。
- [major] R-02 剪贴板异常用例未准备非空缓冲，复制按钮处于 disabled 状态而无法进入异常分支
  - 详情:plan.md 的 A 部分规定缓冲为空时按钮 disabled，TC-17 也验证该约束；但 TC-18/TC-19（plan.md:352-353）没有声明先接收 SSE 内容，默认渲染时按钮仍为空且不可点击，因此无法真实覆盖 clipboard 不存在和 writeText reject。请把两条用例的前置条件改为先向 LogViewer 注入非空日志内容，再点击已启用的复制按钮并断言 error toast 与无未处理拒绝。

## 总评
并发闸、PostgreSQL 行锁竞态、迁移验证和证据档位总体自洽；28 条用例均声明了档位与证据形态，C 档为 0，符合证据契约。当前仍有一个可让 PUT 绕过布尔值防线的关键覆盖缺口，以及两条实际上无法进入目标分支的剪贴板异常用例，因此按 plan-review 规则判定 fail。

VERDICT: fail
