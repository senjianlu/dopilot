# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 将两个互不耦合的需求合并为单个 rawf 任务和提交，违反单主题提交约束
  - 详情:plan.md:14-15、335-337 明确要求两个独立需求共用一次评审和单次提交；但 AGENTS.md:146 要求“一次提交一个主题”，rawf-report/SKILL.md:23 又规定每个任务单次提交。当前任务结构无法同时满足两项约束，应在确认闸前拆成两个 rawf 任务，各自维护 plan、证据、评审和提交。
- [major] R-02 下载方案未释放流式响应持有的数据库会话，慢下载会长期占用连接池
  - 详情:A1 只描述查询、打开文件并返回 StreamingResponse（plan.md:88-147）。现有 get_current_admin 本身依赖 get_session（auth/dependencies.py:46-50），而 yield 依赖要到响应流结束才清理；tasks.py:45-50、297-300 已明确说明这种写法会在流式响应期间钉住连接。方案须明确在鉴权和日志定位完成、fd 打开后关闭共享请求会话，或设计等效的短生命周期认证/预检依赖，并增加用例证明生成器阻塞时数据库连接已释放。
- [major] R-03 并发上限测试无法约束大于 1 的额度、完整 active 状态集合和更新路径
  - 详情:B2 定义 queued/running/finalizing 均计数，B4/B5 还承诺 PUT 与编辑功能；但 TC-09/10 只覆盖 limit=1 + running，TC-11 只覆盖 complete，TC-08/21 只覆盖创建。硬编码“任意非零上限都按 1”、只统计 running、或完全忽略 PUT/编辑预填的实现都能通过现有用例。应增加 max_concurrency=2 时前两次放行、第三次拒绝的用例，参数化覆盖 queued/running/finalizing，并覆盖后端 PUT 及前端编辑提交/展示。
- [major] R-04 “非 int 返回结构化 400”的设计与 Pydantic 字段定义矛盾且未测试
  - 详情:plan.md:236-242 同时要求非 int 由 service 抛 schedule.invalid_max_concurrency 400，并把请求字段声明为普通 int。Pydantic v2 默认会把部分字符串/整数值浮点数强制转换，其他非法值会在 service 前直接成为 FastAPI 422，无法得到承诺的 400 envelope；TC-08 也只测负数。应明确采用严格且一致的输入策略：若坚持 400，保留原始值供 service 校验或统一映射验证异常；若接受 422，则修改契约，并补字符串、分数、布尔值等非整数输入测试。
- [major] R-05 ADR 回写范围遗漏现有被取代决策及决策索引，会留下互相冲突的持久真相
  - 详情:plan.md:50、257-260 只新增 0022 并修改代码注释，但 docs/decisions/0014-node-strategy-and-push-mode.md:17-18 已明确记录旧 coalesce 口径。docs/decisions/README.md:14-15 要求新 ADR 声明取代旧决策，并在旧文件顶部标注；新增 ADR 也应进入该 README 的索引。应把 0014 和 decisions/README.md 纳入改动范围，并扩展 TC-26 验证部分取代标记、0022 索引及新旧口径一致性。
- [major] R-06 全量后端证据命令缺少 PostgreSQL 环境，按现有 fixture 契约不能得到预期的退出码 0
  - 详情:TC-23 使用未带 DOPILOT_TEST_DATABASE_URL 的全量 pytest 命令（plan.md:313），它会收集现有及新增的 PostgreSQL 用例；conftest.py:552-569 明确规定缺少该变量时 fail 而非 skip。TC-14 的内联环境赋值只对该单条命令生效，不会传给 TC-23。应让 TC-23 使用可执行的 PostgreSQL URL 前缀或把显式 export/setup 命令纳入该条 A 档证据契约，并记录完整输出与退出码。

## 总评
证据表已逐条声明档位与形态，且没有 C 档降级问题；下载快照和 PostgreSQL 行锁主思路也基本成立。但当前任务边界违反 rawf 单主题提交约束，同时存在流式会话架构问题、核心并发语义测试缺口及持久决策冲突，按 plan-review 规则必须 fail。

VERDICT: fail
