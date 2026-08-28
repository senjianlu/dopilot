# Plan 评审:第 14 轮

## 问题清单
- [major] R-01 PostgreSQL 并发用例指定的健康节点会被写入 SQLite，TC-18 无法进入待验证的 active 状态
  - 详情:定位：plan.md:634-640、TC-18（:661）；apps/server/tests/conftest.py:410。方案统一要求调用 `seeder.healthy_node()`，但仓库的 `seeder` fixture 固定绑定 `db_session`（SQLite），TC-18 的触发事务使用 `pg_sessionmaker`，因此 PostgreSQL 中看不到该节点，获准任务仍会成为 `no_target`，核心行锁用例无法得到预期结果。应明确在 `pg_sessionmaker` 创建的 session 内构造 `Seeder` 或直接写入健康 Node，并确保该用例的模板、schedule、节点和触发事务全部位于同一个 PostgreSQL 数据库；保留现有 active 状态断言。
- [major] R-02 下载预检缺少 auth-on bearer 的 HEAD 集成用例，认证部署下的必经链路可能全量测试通过仍不可用
  - 详情:定位：plan.md:123-139、326-339、TC-43/TC-45/TC-46。认证开启时，前端先以 axios bearer 调 HEAD，再换下载令牌导航；但 TC-45 只验证 GET 的 bearer 分支，TC-46 未声明 auth-on 或 bearer，因而不能约束 HEAD 路由复用相同鉴权。HEAD 若遗漏 bearer 回落、只接受下载令牌，现有测试仍可通过，而所有认证部署的下载都会止于 401。应增加 auth-on 下“有效 bearer、无 download_token 的 HEAD 返回 200”及“无凭据返回 401”的 A 档断言。
- [major] R-03 前端用例未覆盖 auth-off 时不得换取下载令牌，且成功路径仍错误地把 getLogSnapshot 当作预检
  - 详情:定位：plan.md:324-345、TC-24（:667）、TC-25、TC-35。方案要求 auth-off 直接以无令牌 URL 导航，但组件用例只有带 `download_token=tok` 的路径；实现若无条件调用 `fetchDownloadToken`，在 auth-off 服务端会收到 400，却仍可能通过当前测试。TC-24 还声明 mock `getLogSnapshot`，与方案已确定的 `probeDownload` HEAD 不一致。应把 TC-24 改为显式设置 auth-on、mock 并断言 `probeDownload`，并新增 auth-off A 档用例：HEAD 成功后不调用 `fetchDownloadToken`，生成的 URL 无 `download_token` 且正常导航。

## 总评
并发闸的事务设计、下载资源生命周期以及证据档位契约总体自洽，44 个 A 档、2 个 B 档、0 个 C 档符合比例与形态要求。但 PostgreSQL 核心用例的数据库前置错误，以及下载鉴权矩阵的两个关键缺口，会导致实现阶段返工或认证模式回归，故本轮判定 fail。

VERDICT: fail
