# 0023:任务目标名模糊搜索走顺序扫,暂不引入 pg_trgm

- 日期:2026-08-28
- 背景:任务列表页此前只有 status 与 build artifact 两个下拉筛选,想找
  "某个目标名跑过哪些任务"只能肉眼翻页。用户要求在任务页支持按目标名
  (`tasks.target`,形如 `demo:alpha`)模糊搜索。实现上必然是
  `target ILIKE '%词%'` 这类前后通配的匹配——而**前后通配吃不到 B-tree
  索引**,因此必须在方案阶段就把性能取舍定下来,而不是等线上变慢再补。

  PostgreSQL 对这类查询的标准解法是 `pg_trgm` 扩展 + trigram GIN 索引,
  能把 `%x%` 从顺序扫降到索引扫。本项目用 `postgres:16`
  (`deploy/docker/docker-compose.yml:110`),而 `pg_trgm` 自 PostgreSQL 13
  起是 **trusted extension**——对目标库有 `CREATE` 权限的普通角色即可
  `CREATE EXTENSION`,**不需要超级用户**。因此"装不上"并不是暂缓的理由,
  取舍必须建立在成本/收益上。

- 决定:
  1. **搜索实现为 `Task.target.ilike('%词%')` 的顺序扫**,`tasks.target`
     **不加任何索引**,也**不引入 `pg_trgm` 扩展**。
  2. 搜索词长度**硬上限 100 字符**(`api/v1/tasks.py` 的
     `MAX_TARGET_QUERY_LEN`),超限返回 400 `task.invalid_query`;Web 端
     搜索框以同值设 `maxLength`,使 UI 无法构造出被拒的请求。
  3. 用户输入中的 LIKE 通配符(`%`、`_`)与转义符本身一律转义
     (`services/executions.py` 的 `_like_contains`),按**字面**匹配。
  4. **复议触发条件**(满足任一即应重新评估上索引):任务列表接口 p95
     超过 1s;或 `tasks` 行数达到百万级。

- 理由(按权重排序):
  1. **写放大与收益方向相反**。`tasks` 是本库最高写入的表之一——执行历史
     "每天增长数万行"(`services/executions.py:326` 的既有注释),而目标名
     搜索是**人工低频**操作。trigram GIN 索引的维护成本落在每一次 INSERT /
     UPDATE 上,常驻;它换来的收益只在管理员偶尔搜索时兑现。为低频读给
     高频写加常驻税,方向是反的。
  2. **收益此刻并不成立**。列表本就服务端分页(单页最多 100 行,见
     `ALLOWED_PAGE_SIZES`),搜索又叠在既有筛选之上,当前数据规模下顺序扫
     的成本远没到需要索引的程度。为尚未出现的负载先付成本,是提前优化。
  3. **迁移仍有部署差异风险(次要)**。`CREATE EXTENSION` 虽为 trusted,
     仍要求执行角色对该库有 `CREATE` 权限。默认 compose 里 `dopilot` 是库
     owner,满足;但由 DBA 预建库并只授受限角色的部署未必满足,那条迁移会
     直接失败。这**不是**主要理由(远弱于第 1 条),但确实存在。
  4. **以后再上的代价很低**。加扩展 + 建 GIN 索引是纯增量迁移,查询语句
     一个字都不用改;而现在就上,第 1 条的写入成本立刻发生。

- 影响:
  - 目标名搜索在极大表上会变慢,这是**已知且被接受**的;上面第 4 条给出了
    何时该回头处理的客观阈值。
  - 与本决策同批落地的还有按 `schedule_id` 的任务下钻(schedules 页 →
    tasks 页带筛选跳转)。那一条**不受**本取舍影响:它是等值匹配,直接吃
    0022 引入的 `ix_tasks_schedule_id_status` 索引,无额外成本。
  - 不改变 0001(scrapydweb 仅作行为参考)、0003(单管理员)、0004(统一镜像
    的两种 Docker 角色)、0006(FastAPI + Next 静态导出)等既有决策。
