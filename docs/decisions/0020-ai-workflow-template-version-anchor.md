# 0020:认领 ai-workflow-template v1.0.0 版本锚点;不采用其 Scrapy 标准栈

- 日期:2026-07-26
- 背景:本仓库 2026-07-24 采用 ai-workflow-template 的 rawf 工作流(见
  [`0018`](0018-adopt-ai-workflow-template.md)),但**未记录采用的模板
  版本**——当时模板尚无版本机制,`.ai-workflow/TEMPLATE-VERSION` 不存在。
  模板于 2026-07-25 发布 v1.0.0,引入 SemVer 发版与 consumer 增量升级机制;
  没有版本锚点的 consumer 只能每次全量比较,升级成本高且易漏。

  经双证据交叉判定,本仓库采用的是模板 commit `48a435a`(2026-07-20,
  v1.0.0 之前的未发版状态):① 时间线——采用日之前模板的最后一个 commit
  即 `48a435a`;② 内容指纹——模板该快照的受管路径全集 20 个文件,本仓库
  侧同名路径不多不少,其中 19 个有内容的文件逐字节一致。
- 决定:
  1. **认领版本**:以 `.ai-workflow/TEMPLATE-VERSION` 记录采用版本,三字段
     取 `version: 1.0.0` / `source:`(模板仓库 URL)/ `adopted: 2026-07-26`。
     `adopted` 取**完成基线对齐之日**而非 07-24 的首次采用日——模板
     README「存量项目迁移」第 3 步规定,存量项目须先完成对 v1.0.0 的全量
     基线对齐才可写入版本,对齐前一律记 `unknown`。07-24 的采用事实由
     `0018` 承载,两者不冲突:`0018` 记"为什么采用 rawf",本记录记
     "采用的是哪个版本、偏离了什么、以后怎么升"。
  2. **不采用 Scrapy 标准栈**,按模板决策 0007 第 4 条三处联动删除:
     `AGENTS.md` 技术栈表不加「爬虫」章节、`.ai-workflow/review-standards.md`
     不加 Scrapy 评审关注点、不建 `.claude/skills/rawf-stack-scrapy/`。
     理由:该栈规定的是 **Scrapy 应用项目**的标准(Postgres + SQLAlchemy
     数据层、`.egg` → GitHub Release → scrapyd `addversion.json` /
     `schedule.json` 三段部署链路);dopilot 是**调度这类项目的平台**,三个
     可部署单元为 FastAPI + Next.js,仓库内唯一的 Scrapy 代码是
     `examples/scrapy_clock/`(演示 `.egg` 链路的最小示例,不承载业务)。
     照搬会把 dopilot 的技术栈表述错,并让评审按无关标准打分;残留半套
     更会误导评审与开发,故三处必须同去同留。
  3. **后续升级流程**以模板 README「版本与升级」为权威操作指引:在模板
     仓库的**独立克隆**中 `git checkout --detach "v$NEW"` 锚定快照,读
     `git diff "v$OLD..v$NEW"`($OLD 取自本仓库的 `TEMPLATE-VERSION`),
     可整体替换类整目录拷入覆盖、需人工合并类按 CHANGELOG 升级指引逐文件
     处理,最后更新 `TEMPLATE-VERSION`。**本仓库不添加模板 remote、不 fetch
     模板 tag**(git 历史与模板不同源,fetch 会造成 tag 冲突)。
  4. 被否备选:①「全量认领 v1.0.0 字面」(受管文件与模板零差异、升级
     diff 最干净,但 AGENTS.md 会声明 dopilot 并不使用的数据层与部署链路,
     技术栈表述失真);②「只保留 Scrapy 评审关注点、不加栈章节与 skill」
     (违反 0007 的三处联动规则,留下半套无主约定)。
- 影响:
  - **有意偏离清单(升级时不得被"顺手对齐"掉)**。下次升级若发现下列差异,
    是本决策的结果,不是漏对齐:

    | 编号 | 文件 | 偏离 | 理由 |
    |---|---|---|---|
    | D-1 | `.ai-workflow/review-standards.md` | 缺 v1.0.0 的 Scrapy 评审关注点 4 行 | 三处联动删除;该处有 `<!-- TEMPLATE: 按需删减。 -->` 注释显式授权裁剪 |
    | D-2 | `CLAUDE.md` | 少一处 "(机制见 docs/decisions/0003)" 尾注 | 该引用指向**模板仓库**的 0003(可配置评审轮数上限);本仓库的 `0003` 是「单管理员」,照抄会指向错误文档 |
    | D-3 | `AGENTS.md` | 无「技术栈 > 爬虫」章节 | 同 D-1;dopilot 非 Scrapy 应用 |
    | D-4 | `.claude/skills/rawf-stack-scrapy/` | 整个 skill 目录不存在 | 同 D-1;dopilot 不承载 Scrapy 应用的初始化/编码/测试约定 |
    | D-5 | `AGENTS.md` / `README.md` / `.agents/skills/` / `skills-lock.json` | 与模板结构性不同源 | 属「需人工合并」类:前两者已按项目重写(dopilot 的 README 是产品文档,模板 README 是模板使用说明);后两者模板 v1.0.0 侧不存在,无可并项 |

  - **不承载模板自身产物**:模板的 `CHANGELOG.md`、`README.md`、
    `docs/decisions/0007` `0008`、`.ai/2026-07-25/*`、`logo.svg` 属模板仓库
    的版本历史与使用说明,不在 consumer 受管路径内,不拷入。`.codex/agents/`
    亦不在受管路径清单内,故不引入。
  - 本次对齐的逐文件核验与「需人工合并」类的逐 hunk 处置台账见
    `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/`。
