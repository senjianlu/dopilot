# 09 · Python 包重命名（scrapydweb → dopilot）影响面

> 面向 dopilot 改造工程师。对应路线图阶段 0 任务"改名 scrapydweb→dopilot"（`docs/dopilot/10-roadmap.md:34`，状态 🟡 待评估）与开放问题 6（`10-roadmap.md:93`）。
>
> 本文先用 Grep/Read 系统盘点真实代码的耦合点，再给出"全量改包 vs 仅改 UI/命令"的权衡、推荐策略、分步 checklist 与开放问题。
>
> 阅读约定：**【现状事实】**= 已核实代码，附 `file:line`；**【建议/开放问题】**= 改造判断，可讨论。

---

## 0. 结论速览（TL;DR）

| 维度 | 结论 |
|---|---|
| 包内绝对 `from scrapydweb...` import | **仅 5 处**，全在 `run.py:12-16`；其余 86 处全是相对 import，**不受改名影响** |
| 真正的硬骨头 | ① `static/v160/` 目录名与 `__version__` 强绑定；② `templates/scrapydweb/` 子目录名 + 29 处（28 行）`'scrapydweb/xxx.html'` 字符串引用；③ 配置文件名 `scrapydweb_settings_v11.py`；④ MySQL/PG 库名前缀 `scrapydweb_*`（物理契约） |
| 不可改（对外契约） | `SCRAPYDWEB_BIND/PORT`、配置文件名、MySQL/PG 库名、check_update 埋点参数名 `scrapydweb=`（详见 §7） |
| 可安全改 | UI 文案 `ScrapydWeb`、命令名、`logger` name、临时目录前缀、demo 资源名 |
| 推荐 | **阶段 0 分两步**：先做"低风险表层改名"（命令名 + UI 文案 + 顶层目录壳），**暂缓**包目录与配置文件名的全量改包，留到阶段 0 末或与前端分离一起做（见 §5） |

---

## 1. 包内 import 规模（grep 统计）

【现状事实】整包 `.py` 中 `scrapydweb` 字样命中 **94 行 / 29 个文件**（按行计；含注释/字符串，出现约 102 次）。但区分 import 形态后，改名压力远小于命中数暗示的规模：

| import 形态 | 数量 | 位置 | 改名是否受影响 |
|---|---|---|---|
| 相对 import `from .` / `from ..` / `from ...` | **86** | 全包（`common.py:14`、`utils/check_app_config.py:7-16`、`views/**/*.py` 等） | **不受影响**（相对路径与包名解耦，改目录名即可） |
| 绝对 import `from scrapydweb ...` | **5** | `run.py:12,13,14,15,16` | 受影响，需逐行改 |
| 绝对 import `import scrapydweb` | **0** | —— | —— |

绝对 import 全文（`run.py:12-16`）：

```python
from scrapydweb import create_app
from scrapydweb.__version__ import __description__, __version__
from scrapydweb.common import authenticate, find_scrapydweb_settings_py, handle_metadata, handle_slash
from scrapydweb.vars import ROOT_DIR, SCRAPYDWEB_SETTINGS_PY, SCHEDULER_STATE_DICT, STATE_PAUSED, STATE_RUNNING
from scrapydweb.utils.check_app_config import check_app_config
```

【现状事实】另有 1 处字符串形式的绝对包引用（非 import，但 Flask 靠它加载配置类）：

```python
# scrapydweb/__init__.py:70
app.config.from_object('scrapydweb.default_settings')
```

> 【建议】因相对 import 占绝对多数，**重命名包目录 `scrapydweb/ → dopilot/`** 后，仅需改 `run.py` 的 5 行 + `__init__.py:70` 这一字符串，即可让 import 层完整跑通。import 不是难点。

---

## 2. setup.py：packages / package_data / entry_points

【现状事实】`setup.py` 关键耦合点：

| 项 | 位置 | 现状 | 改名动作 |
|---|---|---|---|
| 读版本元数据 | `setup.py:12` | `open(os.path.join(CURRENT_DIR, 'scrapydweb', '__version__.py'))` | 路径 `'scrapydweb'`→`'dopilot'` |
| `name` | `setup.py:20` | `about['__title__']`（= `__version__.py:3` 的 `'scrapydweb'`） | 改 `__version__.py:3` `__title__` |
| `packages` | `setup.py:31` | `find_packages(exclude=("tests",))`（**自动发现**，不写死包名） | 改目录名后自动跟随，无需改 setup.py |
| `package_data` | —— | **未显式声明**；靠 `include_package_data=True`（`setup.py:32`）+ `MANIFEST.in` | 见下 §2.1 |
| `entry_points.console_scripts` | `setup.py:59-63` | `"scrapydweb = scrapydweb.run:main"` | 命令名 + 模块路径都要改 |

`entry_points` 现状：

```python
entry_points={
    "console_scripts": {
        "scrapydweb = scrapydweb.run:main"   # setup.py:61
    }
},
```

> 【建议】改为 `"dopilot = dopilot.run:main"`。命令名 `dopilot` 是**对外 CLI 契约**：阶段 0 Docker 镜像 `CMD`、文档、运维脚本都会引用，应一次定稿。可选保留 `scrapydweb` 旧命令名作过渡别名（多写一行 `"scrapydweb = dopilot.run:main"`），但单管理员私有平台通常无此必要。

### 2.1 MANIFEST.in（package_data 的真实来源）

【现状事实】`MANIFEST.in` 全文含 5 处包路径前缀：

```
include scrapydweb/data/parse/ScrapydWeb_demo.log
include scrapydweb/data/demo_projects/ScrapydWeb_demo/scrapy.cfg
graft scrapydweb/static
graft scrapydweb/templates
graft scrapydweb/data/demo_projects/ScrapydWeb_demo/ScrapydWeb_demo
```

> 【建议】改目录名后这 5 行的 `scrapydweb/` 前缀全部要改。`ScrapydWeb_demo*` 是 demo scrapy 工程名（可改可不改，见 §6）。

---

## 3. static 目录名 `v160` 与 `__version__` 的强绑定（高风险）

这是改名最隐蔽的耦合，**与改包名正交但必须同时理解**。

【现状事实】链路如下：

| 环节 | 位置 | 内容 |
|---|---|---|
| 版本号源 | `__version__.py:4` | `__version__ = '1.6.0'` |
| 拼 VERSION | `__init__.py:302` | `VERSION = 'v' + __version__.replace('.', '')` → 运行期得到 `'v160'` |
| 注入模板 | `__init__.py:316-346` | 所有 `static_css_* / static_js_* / static_icon_*` 用 `url_for('static', filename='%s/css/...' % VERSION)` |
| 物理目录 | `scrapydweb/static/v160/` | 唯一一个版本子目录（`ls static/` 仅有 `v160`） |
| 模板消费 | `base.html:9,11,...`、各 `templates/scrapydweb/*.html` | `<link href="{{ static_css_style }}">` 等，**不直接写 v160**，全走注入变量 |

> 注意：注释里残留 `# VERSION = 'v131dev'`（`__init__.py:304`），说明历史上发版时会**手动同步**目录名与版本号。
>
> **关键风险**：物理目录名 `v160` 由 `__version__='1.6.0'` 运行期推导而来。
> - **只改包名、不改 `__version__`** → `VERSION` 仍是 `'v160'`，static 目录无需动。**安全**。
> - **若顺手改 `__version__`**（如想标记 dopilot 自己的 `0.1.0`）→ `VERSION` 变 `'v010'`，但磁盘目录还是 `v160` → **所有 CSS/JS/icon 404，整站裸奔**。

【建议】

1. 阶段 0 改包名时**不要动 `__version__`**，static 目录零改动，规避 404。
2. 若日后要给 dopilot 独立版本号，必须**同时重命名物理目录** `static/v160 → static/v<新版号无点>`，并同步 `MANIFEST.in` 的 `graft` 与 docs §6.2 引用的 `static/v160/...`。
3. 更彻底的解法（开放问题）：解除 static 目录与版本号的耦合，改用固定目录名 + 构建期 hash 做缓存击穿（与 `06-frontend-rewrite.md` 的 Vite 产物指纹方案天然契合）。**建议留给前端重构阶段**，不在改名任务里顺带做。

---

## 4. templates/scrapydweb 子目录名（第二处目录耦合）

【现状事实】除包目录外，模板里还藏着一个 `scrapydweb` 目录名：

| 项 | 位置 | 内容 |
|---|---|---|
| 物理子目录 | `scrapydweb/templates/scrapydweb/`（34 个 html） | 实际模板都在这层 |
| 字符串引用 | **29 处（28 行；`views/baseview.py:239` 一行含 2 处）** `'scrapydweb/xxx.html'` | `views/**/*.py` 的 `self.template = 'scrapydweb/...'`、`render_template('scrapydweb/...')`、`views/baseview.py:239` 的 `template_fail` |

代表样本：`views/dashboard/jobs.py:78-82`、`views/files/projects.py:57-121`、`views/baseview.py:239`。

> 【建议】若改 `templates/scrapydweb → templates/dopilot`，需同步替换全部 29 处字符串前缀（可脚本批量 `sed 's#scrapydweb/#dopilot/#'` 限定模板字符串上下文）。
>
> **此项可暂缓**：模板子目录名是纯内部约定，不对外、不进契约。优先级低于命令名/UI 文案。前端走 strangler 迁移到 Vue（`06-frontend-rewrite.md`）后这批 Jinja 模板会逐页退场，**没必要为将死的模板做一次性大改名**。

---

## 5. 配置文件名 `scrapydweb_settings_v11.py`（对外契约）

【现状事实】

| 项 | 位置 | 内容 |
|---|---|---|
| 文件名常量 | `vars.py:29` | `SCRAPYDWEB_SETTINGS_PY = 'scrapydweb_settings_v11.py'` |
| 动态导入 | `vars.py:32` | `importlib.import_module(os.path.splitext(SCRAPYDWEB_SETTINGS_PY)[0])` → 模块名 `scrapydweb_settings_v11` |
| 查找/生成 | `run.py:124,131,133,138,150` | `find_scrapydweb_settings_py(...)`；缺失时从 `default_settings.py` copy 一份 |
| 路径配置键 | `run.py:37,48`、`baseview.py:52` | `app.config['SCRAPYDWEB_SETTINGS_PY_PATH']` |

> 【现状事实/契约性】该文件是**用户工作目录下的外置配置文件**，由用户编辑、被 `importlib` 按模块名导入。文件名 = 已部署实例的磁盘文件 = 对外契约。改名会让**现有部署的配置文件失联**（找不到 → 重新 copy 一份默认值 → 用户的自定义配置静默丢失）。
>
> 【建议】
> - dopilot 是**全新私有部署、无存量用户**（fork 自上游，自身无历史实例），因此改名**无迁移包袱**，可放心改为 `dopilot_settings_v1.py`（顺手把 `_v11` 版本后缀也定为 dopilot 自己的语义）。
> - 但因它是契约面，**只改一次、文档同步**：需同步 `vars.py:29` 常量、`08-docker-deployment.md` 里挂载/生成配置的路径、Docker `WORKDIR` 约定。
> - `default_settings.py` 本身**不改名**（它是包内模块，被 `__init__.py:70` 字符串引用 + `run.py` 当作模板 copy 源），只随包目录改名跟随。

---

## 6. Metadata.version 作为唯一键的迁移影响

【现状事实】先厘清一个常见误解：**`Metadata.version` 存的不是包名，而是 `__version__`（值 `'1.6.0'`）**。

| 项 | 位置 | 内容 |
|---|---|---|
| 字段定义 | `models.py:21` | `version = db.Column(db.String(20), unique=True, nullable=False)` |
| 唯一键写入 | `__init__.py:135-136` | `if not Metadata.query.filter_by(version=__version__).first(): metadata = Metadata(version=__version__)` |
| 单例读写入口 | `common.py:85` | `handle_metadata()` 全靠 `filter_by(version=__version__).first()` 定位**那一行**单例 |

`Metadata` 单行承载平台级单例状态：`pageview`、`last_check_update_timestamp`、`main_pid/logparser_pid/poll_pid`、`username/password`、`scheduler_state`、`jobs_per_page`、`url_scrapydweb/url_jobs/...`（`models.py:20-36`）。

> **结论**：
> - **改包名 `scrapydweb→dopilot` 完全不触碰 `Metadata`**（version 值与包名无关）。✅ 零影响。
> - **真正有迁移风险的是改 `__version__`**：一旦 `__version__` 从 `'1.6.0'` 变（如 dopilot 想用 `'0.1.0'`），`filter_by(version=新值).first()` 找不到旧行 → `__init__.py:135` 走到**新建一行**分支 → 旧的 pageview/认证/scheduler_state/url 单例**全部回到默认值**（视觉上像"配置被重置"）。
>
> 【建议】
> - 改名任务里**不改 `__version__`**（与 §3 static 结论一致），Metadata 零风险。
> - 若日后要切 dopilot 自有版本号，需写一次性迁移：把旧 version 行的 `version` 字段 UPDATE 成新值（而非让代码新建行），避免单例状态丢失。属阶段 0 末或独立小任务。

---

## 7. 后端契约 / 环境变量前缀 SCRAPYDWEB_*（不可改 vs 仅文案可改）

依据 `docs/architecture/04-views-and-frontend.md` §6.2（`04-views-and-frontend.md:271-289`）的判定原则：**UI 文案可改，后端契约变量不可改**。逐项核实如下。

### 7.1 不可改（对外契约，改了破坏部署/数据/埋点）

| 标识 | 位置 | 契约性质 |
|---|---|---|
| `SCRAPYDWEB_BIND` / `SCRAPYDWEB_PORT` | `default_settings.py:18,20`；`check_app_config.py:66-73,93-95`；`baseview.py:82-83`；`run.py:116,119,156-164` | **配置键**，用户外置配置文件里写的就是这俩名字；改名 = 现有配置失效 |
| `SCRAPYDWEB_SETTINGS_PY` 文件名 | `vars.py:29`（见 §5） | 磁盘配置文件名契约 |
| MySQL/PG 库名 `scrapydweb_apscheduler/_timertasks/_metadata/_jobs` | `utils/setup_database.py:7-11` | **物理数据库实例名**；改名需对已建库执行 `RENAME DATABASE`/迁移，否则连不上旧数据 |
| `SCRAPYDWEB_TESTMODE` | `utils/setup_database.py:17` | 测试环境变量，CI/测试脚本引用 |
| check_update 埋点参数名 `scrapydweb=` | `templates/scrapydweb/jobs*.html:18/42`、`servers.html:38` | 指向 `my8100.pythonanywhere.com/check_update`，URL query key 名（见下，dopilot 应直接移除整个埋点） |
| `URL_SCRAPYDWEB` / `url_scrapydweb` | `check_app_config.py:95-97`、`baseview.py:93`、`poll.py:48-52`、`views/operations/execute_task.py:21-25,164`、`models.py:27` | 跨进程（poll 子进程、execute_task）传递的 config/metadata 键名，**内部 RPC 契约**，改需全链路同步 |
| `SCRAPYDWEB_VERSION` / `scrapydweb_version` | `__init__.py:312`、`baseview.py:12,25`、`settings.py:57` | §6.2:289 明列**不可改**（破坏 metadata/埋点契约） |

> 【建议·埋点】check_update 是上游向 `my8100.pythonanywhere.com` 的**版本统计回传**（`jobs*.html`、`servers.html`），私有平台应**整段删除**这些 `<script src=...check_update...>` 标签 + `checkLatestVersion(...)` 调用，而非纠结参数名改不改。删除即同时消除该处契约。

### 7.2 仅 UI 文案 / 内部名（可安全改）

| 标识 | 位置 | 说明 |
|---|---|---|
| 品牌文案 `ScrapydWeb` | `base.html:7,57`、`base_mobileui.html:7`、`500.html` | §6.2 建议引入 `BRAND_NAME` 注入变量替换（`04-views-and-frontend.md:286`） |
| CLI 启动 banner | `run.py:29,30` | `"ScrapydWeb version: %s"` / `"Use 'scrapydweb -h'..."` 可改文案 |
| `logger` name | `poll.py:20`、`send_email.py:11` | `logging.getLogger('scrapydweb.utils.poll')` 仅日志归类，改不改无功能影响（建议跟随包名改） |
| 临时目录前缀 | `views/operations/scrapyd_deploy.py:67`、`deploy.py:357,361` | `tempfile.mkdtemp(prefix="scrapydweb-...")` 纯本地临时名 |
| demo 资源名 `ScrapydWeb_demo*` | `data/demo_projects/ScrapydWeb_demo*/`、`vars.py`（保护清单）、`parse.py`、`deploy.py`、`baseview.py` | demo scrapy 工程；注意 `vars.py:65` 把 `ScrapydWeb_demo.log` 列入**不删除白名单**，改名要同步否则 demo 文件被清理逻辑误删 |

> 注意 `data/demo_projects/` 下存在 `ScrapydWeb_demo - 副本/` 这种带中文"副本"的脏目录，改名清理时一并处理。

---

## 8. 影响面清单总表（类别 / 位置 / 数量 / 代价）

| # | 类别 | 代表位置 | 数量 | 契约性 | 代价 |
|---|---|---|---|---|---|
| 1 | 相对 import | 全包 `from .`/`..`/`...` | 86 | 内部 | **零**（改目录名自动跟随） |
| 2 | 绝对 import | `run.py:12-16` | 5 | 内部 | 低（逐行改） |
| 3 | 字符串包引用 | `__init__.py:70` `from_object('scrapydweb.default_settings')` | 1 | 内部 | 低 |
| 4 | setup.py | `:12,61`（version 路径、entry_points） | 2 | CLI 命令=契约 | 低，但命令名要定稿 |
| 5 | MANIFEST.in | 5 行包路径前缀 | 5 | 内部 | 低 |
| 6 | static/v160 目录 | `__init__.py:302` + 物理目录 | 1 目录 | —— | 0（不改 `__version__` 即免动）/ 高（动了要重命名目录+全链路） |
| 7 | templates/scrapydweb 子目录 | 物理目录 + 29 处 `'scrapydweb/*.html'` | 1+29 | 内部 | 中（批量替换）；**建议暂缓** |
| 8 | 配置文件名 | `vars.py:29` + `run.py` 5 处 | ~6 | **对外契约** | 中（无存量，可一次改净） |
| 9 | MySQL/PG 库名 | `setup_database.py:7-11` | 4 常量 | **物理契约** | 高（有存量需迁移）/ 0（新部署） |
| 10 | `SCRAPYDWEB_BIND/PORT` 等配置键 | `default_settings.py:18,20` 等 | 多处 | **对外契约** | **不改** |
| 11 | `SCRAPYDWEB_VERSION` 埋点 | `__init__.py:312` 等 | 多处 | **对外契约** | **不改**（埋点整段删） |
| 12 | UI 品牌文案 | `base.html:7,57` 等 | ~6 处 | 文案 | 低（引入 `BRAND_NAME`） |
| 13 | logger/临时目录/demo 名 | `poll.py:20` 等 | 散 | 内部 | 低（可选） |
| 14 | Metadata.version | `models.py:21`、`__init__.py:135` | —— | 数据 | **改包名零影响**；改 `__version__` 才有迁移风险 |

---

## 9. 改名 vs 暂缓的权衡

| 选项 | 范围 | 收益 | 代价/风险 | 适用 |
|---|---|---|---|---|
| **A 全量改包** | 包目录 + 模板子目录 + 配置文件名 + 库名 + 全部内部名 | 仓库内"scrapydweb"基本绝迹，新人零困惑；契约面一次定稿 | 一次性 diff 巨大，与并行的执行器/前端改造易冲突；static/version、Metadata 若误碰即翻车 | 团队能冻结其他改动、单独排一个 PR 时 |
| **B 仅 UI/命令名** | entry_points 命令名 + `BRAND_NAME` 文案 + 删埋点 + CLI banner | 改动小、风险低、用户/运维侧立刻看到"dopilot" | 包目录、模板目录、import 仍是 `scrapydweb`，代码层观感不变 | 想最快出对外效果、内部容忍度高时 |
| **C 分两步（推荐）** | 先 B；包目录+配置文件名留到阶段 0 末单独 PR；模板目录随前端 strangler 自然消亡 | 兼顾对外效果与低风险；避免与执行器/前端大改撞车 | 中间态仓库里包名仍 `scrapydweb`，需在 docs 注明"内部包名待改" | dopilot 当前阶段 |

> 决策依据：dopilot **无存量线上实例**（fork 自上游、自身全新部署），所以契约面"破坏迁移"的风险点（配置文件名 §5、库名 §9）在 dopilot 语境下**不是迁移问题、只是定稿问题**——这降低了全量改包的难度，但**与阶段 0 并行的执行器抽象（`01-gap`）和前端重构（`06`）才是冲突源**。结论：风险不在"能不能改名"，而在"何时改、避免与大改撞 PR"。

---

## 10. 推荐策略（结合阶段 0）

对应 `10-roadmap.md:34` 的 🟡 任务，建议拆成两个子任务落 backlog：

**阶段 0 早期 · 表层改名（低风险，先做）**
1. entry_points 命令名 `scrapydweb → dopilot`（`setup.py:61`）+ `__version__.py:3` `__title__`。
2. 引入 `BRAND_NAME` 注入变量（§6.2:286），替换 `base.html:7,57`、`base_mobileui.html:7`、`500.html` 的 `ScrapydWeb` 文案。
3. 删除 check_update 埋点（`jobs*.html`、`servers.html`）+ 改 CLI banner（`run.py:29,30`）。
4. **明确不动**：`SCRAPYDWEB_BIND/PORT`、`SCRAPYDWEB_VERSION`、`__version__`、static/v160、Metadata、库名。

**阶段 0 末期 · 包目录改名（与执行器/前端大改不并行时单独 PR）**
5. `git mv scrapydweb/ dopilot/`；改 `run.py:12-16`（5 行绝对 import）+ `__init__.py:70` 字符串。
6. 改 `setup.py:12` version 路径 + `MANIFEST.in` 5 行前缀。
7. 改配置文件名 `vars.py:29` → `dopilot_settings_v1.py`，同步 `08-docker-deployment.md`。
8. （新部署）改库名常量 `setup_database.py:7-11`。
9. logger name / 临时目录前缀 / demo 工程名跟随改（可选）。

**留给后续阶段（不在改名任务内）**
10. `templates/scrapydweb/` 子目录 + 29 处字符串：随前端 strangler 迁移自然退场（`06-frontend-rewrite.md`），不单独改。
11. 解除 static 目录与 `__version__` 耦合：并入前端 Vite 构建指纹方案。
12. dopilot 自有 `__version__` + Metadata 行迁移脚本：作为独立小任务。

---

## 11. 分步改名 checklist

表层改名（子任务 1）：

- [ ] `setup.py:61` entry_points：`scrapydweb = scrapydweb.run:main` → `dopilot = dopilot.run:main`（包目录未改前可暂用 `dopilot = scrapydweb.run:main`）
- [ ] `__version__.py:3` `__title__ = 'dopilot'`
- [ ] `__init__.py` `inject_variable()` 注入 `BRAND_NAME='dopilot'`；模板 `base.html:7,57`、`base_mobileui.html:7`、`500.html` 改用 `{{ BRAND_NAME }}`
- [ ] 删 `jobs.html/jobs_classic.html/jobs_mobileui.html/servers.html` 的 check_update `<script>` 与 `checkLatestVersion(...)`
- [ ] `run.py:29,30` banner 文案改 dopilot
- [ ] 自检：`grep -rn "ScrapydWeb" templates/`（应只剩待删的模板子目录路径，无 UI 文案）

包目录改名（子任务 2）：

- [ ] `git mv scrapydweb dopilot`
- [ ] `run.py:12,13,14,15,16` 五行 `from scrapydweb` → `from dopilot`
- [ ] `__init__.py:70` `'scrapydweb.default_settings'` → `'dopilot.default_settings'`
- [ ] `setup.py:12` 路径 `'scrapydweb'` → `'dopilot'`
- [ ] `MANIFEST.in` 5 行前缀 `scrapydweb/` → `dopilot/`
- [ ] `vars.py:29` 配置文件名 → `dopilot_settings_v1.py`；同步 `vars.py:32` 导入逻辑无需改（依赖常量）
- [ ] （新部署）`setup_database.py:7-10` 四个 `DB_*` 前缀 → `dopilot_*`
- [ ] `poll.py:20`/`send_email.py:11` logger name、`deploy.py:357,361`/`scrapyd_deploy.py:67` 临时目录前缀（可选）
- [ ] **验证 `__version__` 未改** → 确认 `VERSION` 仍 `'v160'`、static 目录无需动、Metadata 不新建行
- [ ] 烟测：`pip install -e .` → `dopilot` 命令能起 → 首页 CSS/JS 200（验证 static）→ 登录态/pageview 保留（验证 Metadata）→ DB 连接正常

---

## 12. 开放问题

1. **命令名是否保留 `scrapydweb` 别名过渡？** 单管理员私有平台倾向不保留；若有现成运维脚本依赖则保留一版。
2. **`__version__` 何时切到 dopilot 自有版本号？** 一旦切，必须同步 static 目录重命名（§3）+ Metadata 行迁移脚本（§6），不能裸切。建议独立任务。
3. **static 目录与版本号解耦的时机**：随前端 Vite 重构（`06`）一起做，还是改名时顺手做？倾向前者，避免改名 PR 膨胀。
4. **模板子目录 `templates/scrapydweb/` 改不改**：若前端 strangler 周期较长，中间态保留 `scrapydweb` 模板目录名是否可接受？（本文倾向接受，不为将死代码改名。）
5. **MySQL/PG 库名前缀**：若未来 dopilot 与其它系统共库，`dopilot_*` 前缀是否需要再加 schema 隔离？
6. **`URL_SCRAPYDWEB` 等内部 RPC 键名**（poll/execute_task 跨进程传递）改名收益低、链路广，是否纳入包目录改名 PR，还是永久保留？建议保留（纯内部、改名无外部收益）。
