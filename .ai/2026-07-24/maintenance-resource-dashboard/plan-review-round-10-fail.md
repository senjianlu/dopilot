# Plan 评审:第 10 轮

## 问题清单
- [plan-blocker] R-01 PostgreSQL 表大小查询使用了不成立的函数参数类型。
  - 详情:定位：§2 postgres 板块规定调用 `pg_total_relation_size(quote_ident(...))`。`quote_ident()` 返回 text，而 `pg_total_relation_size` 接收 regclass；文本表达式不会像字符串字面量一样可靠地解析为 regclass，真 PostgreSQL 路径会因函数签名不匹配而使整个 postgres scope 降级。应改为参数化调用 `pg_total_relation_size(to_regclass(:qualified_name))`，或将白名单表名安全转换为 regclass；同时保留 TC-17 对真实 PostgreSQL 路径的验证。
- [major] R-02 新增运维操作端点的认证与异常契约测试覆盖不完整。
  - 详情:定位：TC-05、TC-06。方案声明两个 POST 端点均强制 admin 认证，但测试只在 GET resource-stats 上验证无 token→401，没有验证 destructive 的 sweep-now 和 BGREWRITEAOF 端点拒绝未认证请求；此外 rewrite-aof 契约明确“调用异常也返回 503”，TC-06 仅覆盖 app.state 无 Redis，未覆盖 Redis 存在但 `bgrewriteaof()` 抛错。应为两个 POST 端点逐一增加未认证分支，并为 rewrite-aof 增加调用异常→503 错误信封的用例。

## 总评
方案整体与 rawf 闸门、证据档位和既有单实例/异步架构基本一致，17 条用例均逐条声明了档位与证据形态，C 档为 0。当前仍有一处会令真实 PostgreSQL 采样失败的方案级 SQL 错误，以及新增安全操作 API 的关键异常路径测试缺口，因此本轮判定 fail。

VERDICT: fail
