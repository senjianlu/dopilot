# Plan 评审:第 04 轮

## 问题清单
- [plan-blocker] R-01 并发闸会使用锁前读取的旧上限，运行中修改 max_concurrency 后仍可能穿透新限制
  - 详情:plan.md:285-303 先以传入 Schedule 的 max_concurrency==0 决定无锁放行，随后即使执行 SELECT ... FOR UPDATE，也未要求用锁下结果刷新 SQLAlchemy identity map。若触发请求先读到 0，另一事务随后把上限改为 1 并提交，旧请求仍会在更新 API 返回后无锁建单；非零旧值在等待行锁期间被修改时也可能继续参与判断。仓库现有锁查询已明确使用 execution_options(populate_existing=True) 刷新旧实例（services/executions.py:276-280）。应改为始终先锁定并刷新 schedule 行，再基于锁下的 max_concurrency 判断是否为 0，同时处理行已删除及 fire_timer 锁下发现已禁用的情况；调用方后续也应使用该锁下实例。另需增加 PostgreSQL 协调用例，覆盖“触发已读取旧值→并发更新上限并提交→触发继续”的线性化结果，TC-18 的两个触发并发无法发现此缺陷。
- [major] R-02 普通 int schema 与 isinstance 校验会把布尔值静默接受为并发上限，且现有测试未覆盖
  - 详情:plan.md:323-341 将类型非法输入定义为 422，并声称 service 会验证 int；但 Pydantic v2 的普通 int 会把 JSON true/false 收敛为 1/0，进入 service 后原始类型已丢失，而 isinstance(True, int) 本身也为真。于是 true 会成为上限 1，false 会意外开启“不限”，违反整数输入契约。TC-11 仅覆盖 "abc" 和 1.5，无法发现该路径。应明确布尔值契约；若应拒绝，schema 需在转换前拒绝 bool，service 也需显式排除 bool，并为 POST、PUT或直接 service 路径补充自动化用例。

## 总评
证据表已逐条声明档位和证据形态，30 条 A、2 条 B、0 条 C 的分配合规，下载异常与资源生命周期覆盖也较完整。当前仍有一处会实际穿透新并发限制的行锁设计错误，以及一个未被测试约束的输入类型漏洞，因此按 plan-review 规则判定 fail。

VERDICT: fail
