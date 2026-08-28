# Plan 评审:第 15 轮

## 问题清单
- [plan-blocker] R-01 并发维护截断不一定产生短读，当前方案可能静默交付被改写却长度正确的日志快照
  - 详情:定位：plan.md:216-252、TC-08，以及 services/maintenance.py:337-350。方案假定 `_truncate_file` 后文件必然短于 `snapshot_size`，从而依靠 Content-Length 不足让下载失败；但真实实现会先截到 `cap`，再写入 maintenance marker。若预检时文件大小为 `cap+1` 等小幅超限值，维护后大小会变成 `cap+len(marker)`，可能仍大于原 `snapshot_size`。分块重开文件的读取器此时会读满原长度，其中尾部已被 marker 替换，不会遇到 EOF，浏览器却会把被改写的内容当作成功下载。TC-08 仅做纯 truncate，没有调用真实 `_truncate_file`，无法发现该路径。须重新设计快照与维护截断的协调或不可变物化机制，或重新定义并确认下载语义；同时增加调用真实维护截断、覆盖 `cap < before <= cap+len(marker)` 的确定性 A 档用例，保证不会静默成功。
- [major] R-02 max_concurrency 的合法值域没有与 PostgreSQL Integer 的上限对齐
  - 详情:定位：plan.md B1、B4（尤其 509-546）及 TC-10～TC-12。方案声明任意 `int >= 0` 均可正常写入，但模型与迁移使用 SQLAlchemy `Integer`，在 PostgreSQL 中只能容纳有符号 32 位整数；例如 `2147483648` 会通过 Pydantic 和 `_validate_max_concurrency`，最终在提交时触发数据库 DataError/500。应把合法范围明确为 `0..2147483647` 并由 service 返回结构化 400（前端同步设置 max），或改用能承载已声明值域的列类型；补充 POST、PUT 和 service 直调的上界/越界 A 档用例。

## 总评
并发闸、鉴权矩阵及证据契约整体已较完整：47 条用例均声明档位与证据形态，C 档为 0。当前日志快照仍存在会静默成功的数据一致性漏洞，另有数据库整数边界未定义，按 plan-review 规则判定 fail。

VERDICT: fail
