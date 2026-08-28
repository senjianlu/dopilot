# Plan 评审:第 12 轮

## 问题清单
- [major] R-01 下载接口的“bearer 或下载令牌”鉴权契约与路由伪代码及测试覆盖不闭合
  - 详情:定位：plan.md A1/A1-a、TC-05、TC-42、TC-43。方案声明 auth 开启时有效 bearer 与 download_token 二选一，但伪代码没有 download_token 参数且无条件调用 resolve_admin；原生导航只带下载令牌时会先因缺少 bearer 返回 401。反向改成仅验证下载令牌又能通过现有用例，因为没有任何 A 档用例验证 GET 下载接口携带有效 bearer 可以成功。请明确分支顺序：auth off 放行；auth on 时有效且绑定 task 的 download_token 放行，否则调用 resolve_admin 验证 bearer；并增加有效 bearer 下载成功的 A 档用例，确保两条授权路径都被真实约束。
- [major] R-02 前端下载预检建立在现有日志快照接口不会提供的 404 语义上，TC-25 因完全 mock 而形成假覆盖
  - 详情:定位：plan.md A2 第 1 步与 TC-25；现有 apps/server/dopilot_server/api/v1/tasks.py:get_logs 和 logs/files.py:read_slice。方案假定 getLogSnapshot(..., maxBytes: 1) 在日志不存在时抛 404，但现有接口在无 log_file 行时返回 200、status=missing；有索引行但磁盘文件不存在时 read_slice 也返回空内容，通常仍是 200。于是常见的“尚无日志文件”不会触发 toast，而会继续取令牌并导航到返回 404 的下载地址；TC-25 仅让 mock 主动抛 404，无法发现真实契约不匹配。请改用真正检查下载可用性的轻量端点/HEAD，或让下载令牌交换同时按 execution/stream 完成与下载路由一致的文件预检，并增加无 log_file 行和磁盘文件缺失的真实链路 A 档用例。

## 总评
证据契约本身合规：44 条用例均声明了档位和证据形态，A/B/C 为 42/2/0，C 档没有降档或超限问题。并发行锁与迁移方案总体自洽，但下载链路仍有两处会使实现遵循方案后鉴权失败或异常提示失效的契约错误，因此本轮应 fail。

VERDICT: fail
