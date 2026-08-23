# Plan 评审:第 12 轮

## 问题清单
- [plan-blocker] R-01 恢复 runbook 只备份 PostgreSQL，违反日志索引与正文必须成对备份的既有持久化决策。
  - 详情:定位：plan.md:72 的步骤③仅备份 `${P}_dopilot-db`，回滚也只说明恢复该备份；但 `docs/decisions/0007-postgresql-only-log-bodies-on-disk.md:17-18` 与 `docs/architecture/05-deployment.md:80-87` 明确要求 PostgreSQL 和 `${P}_dopilot-server-data`（`/server-data/logs`）缺一不可。本方案的新版本启动后会立即截断/淘汰 server-data 中的日志，若随后回滚，仅恢复 DB 会得到旧索引/offset 对应已被修改或删除正文的不一致状态，且无法恢复被启动清理删除的日志。应在停服后的同一静止点同时备份并成对恢复 `${P}_dopilot-db` 与 `${P}_dopilot-server-data`，写清失败回滚顺序，并给 runbook 增加 A 档静态校验，验证两卷的备份与恢复命令都存在。
- [major] R-02 TC-01i 在 `.pth` 已执行后才改写 `sys.argv`，不能验证生产中的自动激活路径。
  - 详情:定位：plan.md:80 与 TC-01i（plan.md:229）。设计要求 `.pth` 在解释器启动时导入 `dopilot_agent.logcap`，模块当场依据 `sys.argv` 决定是否安装补丁；TC-01i 却描述为在被测脚本内“经 `sys.argv` 赋值”构造 crawler argv。`.pth` 可执行行在 Python 启动期间运行，晚于它的脚本赋值不可能影响已完成的激活判断（[Python `site` 文档](https://docs.python.org/3/library/site.html)）。因此该用例要么按方案必然不激活，要么迫使实现增加一条生产不存在的后置安装路径，仍不能证明核心硬界接线。应让隔离环境中的 Python 进程从真实命令行直接收到 `crawl ... -s LOG_FILE=... -s DOPILOT_JOB_LOG_CAP_BYTES=... -a _job=...`，脚本不改 `sys.argv`、不显式导入 logcap；更稳妥的是实际走已安装 Scrapyd runner 的 argv 形态。
- [major] R-03 把 Hatchling 声明为根 pyproject 的开发依赖既不符合仓库包边界，也不能保证 TC-01i 的无隔离构建可复现。
  - 详情:定位：plan.md:95、TC-01i；AGENTS.md 的目录约定及 `docs/decisions/0005-monorepo-apps-packages.md` 规定根 `pyproject.toml` 只放 pytest/ruff 共用配置、不是可安装包。当前根文件没有 `[project]` 或受现有安装流程消费的依赖组，文档化环境只安装 `packages/protocol`、`apps/server[dev]`、`apps/agent[dev]`；因此“根 dev 依赖加入 hatchling”要么破坏既定根包边界，要么在干净环境中根本不会安装 Hatchling，而 TC-01i 的 `pip wheel --no-build-isolation` 会失败。应把测试所需的 Hatchling 放入 `apps/agent` 的 dev extra（并沿用现有开发安装流程），或改用一个与仓库既有依赖安装契约一致的隔离构建方案；不要把根目录变成安装包。

## 总评
证据契约本身合规：测试表逐条声明了档位和证据形态，全部为可自动化的 A 档，C 档为 0。方案主体已覆盖大量异常与并发路径，但恢复备份边界仍与既有决策冲突，且核心 `.pth` 生产接线用例及其构建依赖目前不可按所述方式提供有效、可复现的验收证据。

VERDICT: fail
