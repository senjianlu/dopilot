# 09 · scrapydweb 行为移植注意事项（耦合点清单）

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。
>
> **本文已重定位**：早期版本以"把 scrapydweb 包改名成 dopilot"为框架（git mv、改 setup.py/vars.py、分两步全量改包、Jinja strangler 共存等），这一立意已整体废弃。dopilot 不由 scrapydweb 原地改名而来，而是按权威 `apps/`+`packages/` 布局**全新编写**，逐域以 scrapydweb 为**行为参考**重写。`reference/scrapydweb/` 只读、不参与 Docker 构建、不被 import、绝不 git mv。
>
> 本文现在是 **scrapydweb 行为/契约移植注意事项**：盘点 scrapydweb 在各功能域上的内部耦合点，作为 dopilot **全新实现**对应功能时"要复刻哪些行为语义、要规避哪些反模式、哪些埋点不移植"的清单。文中 `file:line` 一律是 scrapydweb 行为参考引用（路径相对 `reference/scrapydweb/`），**绝不是 dopilot 的改动目标**。

> **⚠️【历史文档 —— 阶段 2.1 已迁移前端技术栈】** 本文部分内容按**阶段 2.1 之前**的原始前端设计（**Vue 3 + Element Plus + Vite + vue-i18n + Pinia**）撰写，仅作历史/行为移植参考保留，**不再代表当前实现**。当前前端技术栈为 **Next.js（静态导出）+ shadcn/ui + Recharts + react-i18next + TypeScript**，纯静态产物由 dopilot-server 托管；组件源码在 `apps/web/components`、页面在 `apps/web/app`。权威说明见 `docs/dopilot/06-frontend-rewrite.md` 顶部对照表与 `docs/phases/phase-2.1/01-claude-implementation-report.md`。下文涉及前端框架、目录路径、开发服务器、部署与静态资源策略的旧指引，一律以阶段 2.1 为准。

---

## 0. 移植要点速览（TL;DR）

下表区分"dopilot 必须在自有实现里复刻的对外行为契约语义"与"scrapydweb 内部约定、dopilot 不必沿用"。dopilot 的键名/库名/文件名/目录结构均按自身领域命名，下表只关心**语义**是否需要复刻。

| 维度 | scrapydweb 行为 | dopilot 移植注意 |
|---|---|---|
| 配置项语义 | `SCRAPYDWEB_BIND/PORT` 等键承载"绑定地址/端口"等配置语义 | 语义要复刻（dopilot 配置项名自定，由自有 toml 加载器从 `configs/` 读取，见 §5/§7） |
| 配置加载形态 | cwd 下一个硬编码文件名的 Python 模块，按模块名 `importlib` 导入 | **反模式，不移植**；dopilot 用 toml（`configs/server.example.toml`、`agent.example.toml`，经 `DOPILOT_CONFIG` 加载） |
| 数据模型划分 | 数据按 apscheduler/timertasks/metadata/jobs 四类分库 | 数据划分语义可参考（§7），dopilot 库名/schema 自定 |
| 静态资源↔版本耦合 | static 目录名由 `__version__` 运行期推导（高风险，见 §3） | **反模式教训**：dopilot 用前端构建产物指纹解耦版本与物理目录（〔阶段 2.1〕由 Next.js 静态导出产物指纹承担；旧文下方"Vite 指纹"为迁移前措辞） |
| 平台单例状态 | `Metadata` 单行靠 `version` 唯一键承载全平台单例（见 §6） | dopilot 设计等价"平台单例状态"存储时要理解此语义与版本迁移陷阱 |
| 版本统计埋点 | check_update 向 `my8100.pythonanywhere.com` 回传 | **不移植**：dopilot 是私有平台，不实现该回传（§7） |
| 前端 | Jinja 模板渲染页面 | **不移植 Jinja**；前端由 `apps/web` SPA greenfield 实现，直连 `/api/v1`，**无新旧共存**（〔阶段 2.1〕现为 Next.js 静态导出 + shadcn/ui + react-i18next；下文"Vue3+Element Plus+Vite"为迁移前措辞） |

---

## 1. scrapydweb 的 import 组织（中性事实，非 dopilot 依据）

【现状事实】scrapydweb 整包 `.py` 中 `scrapydweb` 字样命中约 94 行 / 29 个文件；其包内 import **以相对 import 为主**（`from .` / `from ..` / `from ...`，约 86 处，如 `common.py:14`、`utils/check_app_config.py:7-16`、`views/**/*.py`），仅 `run.py:12-16` 5 处为绝对 import，另有 1 处字符串形式的包引用 `app.config.from_object('scrapydweb.default_settings')`（`__init__.py:70`）让 Flask 加载配置类。

> 这只是 scrapydweb 自身的代码组织事实，**对 dopilot 的包/模块结构无参考意义**。dopilot 的包与模块结构按 `apps/server/dopilot_server/...`（及 `apps/agent`、`apps/web`、`packages/`）权威布局全新设计，**不参考** scrapydweb 的 import 组织、目录划分或包名。dopilot 内部 import 形态由自身布局决定。

---

## 2. scrapydweb 的打包/分发形态（仅功能层备注）

【现状事实】scrapydweb 用 `setup.py` + `MANIFEST.in` 打包：`find_packages` 自动发现包、`include_package_data=True` + `MANIFEST.in` 的 `graft` 打包 `static/`、`templates/` 及 demo 工程，`entry_points.console_scripts` 暴露**一个 CLI 命令**（`scrapydweb = scrapydweb.run:main`），`__version__.py` 提供 `__title__`/`__version__` 元数据。

> 功能层备注（**不沿用其文件形态**）：dopilot 的对应需求——暴露 CLI 入口、声明依赖、打包前端产物——由 dopilot 自有打包声明承担：`apps/server/pyproject.toml`、`apps/agent/pyproject.toml`（Python 侧）与 `apps/web/package.json`（前端侧）以各自方式声明，**不继承** scrapydweb 的 `setup.py` / `MANIFEST.in` / `entry_points` 形态。dopilot 的 CLI 命令名、模块入口由自身布局定义，与 scrapydweb 无关。

---

## 3. static 目录名 `v160` 与 `__version__` 的强绑定（反模式教训）

这是 scrapydweb 最隐蔽的耦合，作为 dopilot 静态资源/版本管理的**反模式警示**保留。

【现状事实】scrapydweb 的链路如下：

| 环节 | 位置（reference/scrapydweb/） | 内容 |
|---|---|---|
| 版本号源 | `__version__.py:4` | `__version__ = '1.6.0'` |
| 拼 VERSION | `__init__.py:302` | `VERSION = 'v' + __version__.replace('.', '')` → 运行期得到 `'v160'` |
| 注入模板 | `__init__.py:316-346` | 所有 `static_css_* / static_js_* / static_icon_*` 用 `url_for('static', filename='%s/css/...' % VERSION)` |
| 物理目录 | `scrapydweb/static/v160/` | 唯一一个版本子目录（`ls static/` 仅有 `v160`） |
| 模板消费 | `base.html:9,11,...`、各 `templates/scrapydweb/*.html` | `<link href="{{ static_css_style }}">` 等，**不直接写 v160**，全走注入变量 |

> 注意：注释里残留 `# VERSION = 'v131dev'`（`__init__.py:304`），说明历史上发版时会**手动同步**目录名与版本号。
>
> **教训**：物理目录名 `v160` 由 `__version__='1.6.0'` 运行期推导而来。一旦版本号变化而不同步重命名物理目录，`url_for('static', ...)` 拼出的路径就指向不存在的目录 → **所有 CSS/JS/icon 全部 404、整站裸奔**。版本号与静态资源物理布局这种隐式强耦合是脆弱反模式。

【dopilot 移植注意】

- dopilot **不复刻**这种"版本号运行期推导 static 目录名"的耦合。dopilot 前端为 `apps/web` SPA，由**前端构建产物指纹**（content hash）做缓存击穿，物理目录名与应用版本号解耦——正是吸取此教训。（〔阶段 2.1〕指纹由 Next.js 静态导出产物承担；下文"Vite 构建产物指纹"为迁移前措辞，语义一致。）
- dopilot 的版本号是自身领域的版本，不受任何 scrapydweb 物理目录约束。

---

## 4. scrapydweb 的 Jinja 模板（不移植）

【现状事实】scrapydweb 通过 Jinja 渲染页面：模板物理位于 `scrapydweb/templates/scrapydweb/`（34 个 html），后端以 `'scrapydweb/xxx.html'` 字符串引用（`views/**/*.py` 的 `self.template`、`render_template(...)`、`views/baseview.py:239` 的 `template_fail` 等，约 29 处）。

> 【dopilot 移植注意】dopilot **不移植 Jinja 模板**。前端由 `apps/web` SPA **greenfield 全新构建**，直接对接后端 `/api/v1` JSON 端点；后端（`apps/server/dopilot_server`）采用 FastAPI，只产出 `/api/v1` JSON + SSE，不渲染 HTML 页面。（〔阶段 2.1〕SPA 现为 Next.js 静态导出 + shadcn/ui + Recharts + react-i18next + TS，组件在 `apps/web/components`、页面在 `apps/web/app`；本段"Vue3 + Element Plus + Vite + TS"为迁移前措辞。）
>
> dopilot **没有继承来的 Jinja 页面**，因此**不存在**"Jinja 与 Vue 新旧共存的 strangler 迁移""模板逐页退场"这类问题——这些都是改名路线的废弃假设。前端按 `06-frontend-rewrite.md` 的 greenfield SPA 分阶段交付即可。scrapydweb 各页面承载的**功能**（dashboard/jobs、files/projects 等）作为行为参考，由 SPA 重新实现。

---

## 5. scrapydweb 的配置加载形态（反模式，dopilot 用 toml 替代）

【现状事实】scrapydweb 的配置加载：

| 项 | 位置（reference/scrapydweb/） | 内容 |
|---|---|---|
| 文件名常量 | `vars.py:29` | `SCRAPYDWEB_SETTINGS_PY = 'scrapydweb_settings_v11.py'`（文件名 + 版本后缀**硬编码**） |
| 动态导入 | `vars.py:32` | `importlib.import_module(os.path.splitext(SCRAPYDWEB_SETTINGS_PY)[0])` → 按模块名导入 |
| 查找/生成 | `run.py:124,131,133,138,150` | 在 cwd 查找；缺失时从 `default_settings.py` copy 一份 |
| 默认值来源 | `default_settings.py` + `__init__.py:70` `from_object(...)` | 包内默认配置类 |

> 【dopilot 移植注意 · 反模式】scrapydweb 的配置以一个**用户工作目录（cwd）下的 Python 模块**承载，文件名与版本后缀硬编码、按模块名 `importlib` 导入——文件名即"已部署实例的磁盘文件契约"，导致改文件名会让现有配置静默失联。这是 dopilot 要**规避**的反模式。
>
> dopilot 配置由**自有 toml 加载器**从 `configs/` 读取（`configs/server.example.toml`、`configs/agent.example.toml`，经 `DOPILOT_CONFIG` 环境变量指定路径加载），**不继承** scrapydweb 硬编码 settings 文件名、不从 cwd 按模块名 importlib 导入、不依赖包内 `default_settings.py` 模块形态。
>
> scrapydweb `default_settings.py` 中各配置键的**语义**（绑定地址/端口、节点列表、各开关等，见 §7）作为行为参考保留，dopilot 在 toml 里以自身的键名/结构表达等价语义。

---

## 6. Metadata.version 作为唯一键承载平台单例状态（数据模型语义）

作为 dopilot 设计等价"平台单例状态"存储与版本迁移时必须理解的语义保留。

【现状事实】先厘清一个常见误解：scrapydweb 的 **`Metadata.version` 存的不是包名，而是 `__version__`（值 `'1.6.0'`）**。

| 项 | 位置（reference/scrapydweb/） | 内容 |
|---|---|---|
| 字段定义 | `models.py:21` | `version = db.Column(db.String(20), unique=True, nullable=False)` |
| 唯一键写入 | `__init__.py:135-136` | `if not Metadata.query.filter_by(version=__version__).first(): metadata = Metadata(version=__version__)` |
| 单例读写入口 | `common.py:85` | `handle_metadata()` 全靠 `filter_by(version=__version__).first()` 定位**那一行**单例 |

`Metadata` 单行承载平台级单例状态：`pageview`、`last_check_update_timestamp`、`main_pid/logparser_pid/poll_pid`、`username/password`、`scheduler_state`、`jobs_per_page`、`url_scrapydweb/url_jobs/...`（`models.py:20-36`）。

> 【行为语义与陷阱】scrapydweb 用一个**版本号唯一键**定位"那一行"单例：`version` 值一旦变更，`filter_by(version=新值).first()` 找不到旧行 → 走**新建一行**分支 → 旧的 pageview/认证/scheduler_state/url 等单例状态**全部回到默认值**（视觉上像"配置被重置"）。
>
> 【dopilot 移植注意】dopilot 若设计等价的"平台单例状态"存储（如管理员凭据、调度器状态、分页偏好、内部 url 等聚合在单行/单文档），必须理解这一语义：**单例的定位键不应与会变更的版本号绑定**，否则版本迁移会丢失单例状态。dopilot 应以稳定主键定位单例，版本迁移时 UPDATE 而非新建行。键名/存储形态由 dopilot 自定。

---

## 7. scrapydweb 的契约键 / 库名 / 埋点（语义参考，键名 dopilot 自定）

scrapydweb 内部有一批"配置键 / 数据库命名 / 跨进程键 / 埋点"。dopilot 复刻 scrapydweb 行为时，凡属**配置语义 / 数据模型 / 进程间数据流**者要按其语义在新代码里实现（**键名/库名 dopilot 自定，语义复刻**）；凡属纯品牌/埋点者按下文判断。判定方法论参考 `docs/architecture/04-views-and-frontend.md` §6.2。

### 7.1 行为契约语义（dopilot 以自身命名复刻语义）

| scrapydweb 标识 | 位置（reference/scrapydweb/） | 行为语义（dopilot 移植注意） |
|---|---|---|
| `SCRAPYDWEB_BIND` / `SCRAPYDWEB_PORT` | `default_settings.py:18,20`；`check_app_config.py:66-73,93-95`；`baseview.py:82-83`；`run.py:116,119,156-164` | **绑定地址/端口配置项语义**；dopilot 在 toml 中以自有键表达，语义复刻 |
| MySQL/PG 库名 `scrapydweb_apscheduler/_timertasks/_metadata/_jobs` | `utils/setup_database.py:7-11` | **数据按 apscheduler/timertasks/metadata/jobs 四类划分**的数据模型语义；dopilot 库名/schema 自定，划分语义可参考 |
| `SCRAPYDWEB_TESTMODE` | `utils/setup_database.py:17` | **测试环境下控制建库行为**的语义；dopilot 测试建库以自身机制实现 |
| `URL_SCRAPYDWEB` / `url_scrapydweb` | `check_app_config.py:95-97`、`baseview.py:93`、`poll.py:48-52`、`views/operations/execute_task.py:21-25,164`、`models.py:27` | 在 poll 子进程、execute_task **跨进程传递**的 config/metadata 键，体现**内部 RPC 数据流语义**；dopilot 的 server↔agent 等价数据流**不复刻 HTTP RPC/poll 形态**，改由 Redis Streams 三流（`dopilot:agent:{agent_id}:commands` 命令下行、`dopilot:server:agent-events` 状态上行、`dopilot:server:logs` 日志上行）+ HTTP heartbeat 表达，字段由 `packages/protocol/.../streams.py` 共享 schema 承载（见 `refactor/00-redis-streams-agent-communication.md`） |
| `SCRAPYDWEB_VERSION` / `scrapydweb_version` | `__init__.py:312`、`baseview.py:12,25`、`settings.py:57` | scrapydweb 中与 metadata/埋点耦合的版本标识；dopilot 版本标识自定，注意 §6 的单例迁移语义 |

> check_update 是 scrapydweb 向 `my8100.pythonanywhere.com` 的**版本统计回传**（`templates/scrapydweb/jobs*.html:18/42`、`servers.html:38` 的埋点参数 `scrapydweb=`，及 `checkLatestVersion(...)`）。
>
> 【dopilot 移植注意 · 不移植】dopilot 是**私有平台**，**不实现**该版本统计回传——这是"该行为不移植"的功能层判断，dopilot 后端/前端均无此埋点，故也不存在对应的 query key 契约。

### 7.2 "必须保语义 vs 可自由命名"的判定准则

【方法论参考】scrapydweb 标识可分两类，dopilot 复刻其行为时据此判断：

- **属对外行为契约**（改了会破坏部署/数据/埋点）：配置项语义、数据库命名约定、跨进程 RPC 键、版本/metadata 契约——dopilot 必须**按语义实现**（键名虽自定，但行为等价）。
- **属纯展示 / 内部名**（仅观感，无功能契约）：品牌文案 `ScrapydWeb`（`base.html:7,57` 等）、CLI banner（`run.py:29,30`）、`logger` name（`poll.py:20`、`send_email.py:11`）、临时目录前缀（`scrapyd_deploy.py:67`、`deploy.py:357,361`）、demo 资源名 `ScrapydWeb_demo*` 等——dopilot **自由命名**。

> 【品牌名】dopilot 的品牌/显示名由 `apps/web` SPA 与其 i18n 自由处理，不存在"在 Jinja 模板里注入 BRAND_NAME 变量"这类动作（dopilot 无 Jinja 模板）。（〔阶段 2.1〕i18n 现为 react-i18next。）

> 【运行期目录生命周期参考】scrapydweb `vars.py` 在**启动期（import 时）清空** `DATA_PATH` 下 `parse/`、`deploy/`、`schedule/` 目录中的文件，仅保留白名单（如 `ScrapydWeb_demo.log`，`vars.py:65`）。这一"启动清空瞬态目录 + 白名单豁免"的运行期行为，是 dopilot 工作目录**生命周期/持久化设计**的行为参考：dopilot 需明确区分"瞬态可清空目录"与"需持久化目录"（持久化 `database/` 等，见 `08-docker-deployment.md`），并以自身机制实现，不沿用 scrapydweb 的具体目录名/清空逻辑。

---

## 8. 移植要点表（域 / scrapydweb 行为或耦合 / dopilot 移植注意）

| 域 | scrapydweb 行为或耦合 | dopilot 移植注意 |
|---|---|---|
| 包/import 组织 | 以相对 import 为主的包结构（§1） | 不参考；dopilot 按权威 `apps/` 布局自有结构 |
| 打包/分发 | setup.py + MANIFEST.in + entry_points CLI（§2） | 不沿用；dopilot 用各 app 的 pyproject.toml / package.json |
| 静态资源 | static 目录名由 `__version__` 运行期推导（§3，反模式） | 规避；前端构建指纹解耦版本与物理目录（〔阶段 2.1〕Next.js 静态导出产物指纹；下文"Vite"为迁移前措辞） |
| 前端 | Jinja 模板渲染（§4） | 不移植；`apps/web` SPA greenfield，直连 `/api/v1`，无 Jinja 共存（〔阶段 2.1〕Next.js 静态导出 + shadcn/ui + Recharts + react-i18next） |
| 配置加载 | cwd 下硬编码文件名的 Python 模块 importlib 导入（§5，反模式） | 规避；dopilot 自有 toml 加载器从 `configs/` 读 |
| 平台单例 | Metadata 单行靠 version 唯一键承载单例状态（§6） | 复刻"平台单例状态"语义，定位键勿绑版本号 |
| 配置键语义 | `SCRAPYDWEB_BIND/PORT` 等（§7.1） | 语义复刻，键名 dopilot 自定 |
| 数据模型 | 数据分 apscheduler/timertasks/metadata/jobs 四类（§7.1） | 划分语义可参考，库名/schema 自定 |
| 跨进程数据流 | `URL_SCRAPYDWEB` 等在 poll/execute_task 间传递（§7.1） | 等价语义参考；dopilot server↔agent 改走 Redis Streams 三流（commands/agent-events/logs）+ HTTP heartbeat，schema 见 `packages/protocol/.../streams.py`（refactor/00），不复刻 HTTP poll RPC |
| 版本统计埋点 | check_update 回传 my8100（§7） | **不移植**（私有平台） |
| 品牌/内部名 | ScrapydWeb 文案、logger、临时目录、demo 名（§7.2） | 纯展示/内部名，dopilot 自由命名 |
| 运行期目录 | 启动清空 parse/deploy/schedule + 白名单（§7.2） | 工作目录生命周期/持久化设计参考 |
| glibc 依赖 | 子进程父死信号依赖 libc.so.6 prctl（`sub_process.py:38`） | dopilot agent 执行器若复刻进程托管行为，基础镜像须 glibc（slim/debian，非 Alpine），见 `08-docker-deployment.md` |

---

## 9. 为何 dopilot 全新构建而非改名

dopilot **不是**由 scrapydweb 原地改名/git mv 而来。原因与边界（详见 `00-requirements.md` 决策表与 `05-dev-setup-and-known-issues.md` §1 权威布局）：

- dopilot 是 **greenfield** 项目，按 `apps/`（server/agent/web）+ `packages/`（protocol/client）的自有领域 structure-first 布局设计；scrapydweb 的目录结构/模块划分/命名/配置形态**不作为设计依据**。
- `reference/scrapydweb/` 仅作**功能层行为参考**与**测试 oracle**，它**只读**、**绝不 git mv/修改**、**不进 Docker 构建上下文**、**不被 dopilot import**。
- 因此不存在"全量改包 vs 仅改 UI""分两步改名""模板随 strangler 退场"等方案选择——这些都建立在已废弃的"dopilot = scrapydweb 改名"前提上。

dopilot 的工作分解是：按权威布局**新建** `apps/server/dopilot_server`、`apps/agent`、`apps/web`、`packages/`、`configs/` 骨架，再**逐域以 scrapydweb 为行为参考重写**对应功能（配置加载、数据模型、调度、执行器、节点管理、日志聚合、前端 SPA）。

---

## 10. dopilot 移植 checklist（在新骨架中实现，核对 scrapydweb 行为）

以下均是在 **dopilot 自有代码**（`apps/server/dopilot_server/...`、`apps/agent`、`apps/web`）中**新建/实现**，并以 scrapydweb 对应行为为 **oracle** 核对。**不含任何对 `reference/scrapydweb/` 的写操作。**

权威目录布局（新建骨架时使用，权威定义见 `05-dev-setup-and-known-issues.md` §1）。

> **server↔agent 通信模型以 `refactor/00-redis-streams-agent-communication.md` 为准**：server 主动 HTTP（run/status/tail pull）已被破坏性替换为 Redis Streams——server 经 command_outbox 向 `dopilot:agent:{agent_id}:commands` XADD 命令，agent 主动 XREADGROUP 消费命令、主动 XADD 推 `dopilot:server:agent-events`（状态）与 `dopilot:server:logs`（日志），并主动 POST `/api/v1/agents/{agent_id}/heartbeat` 汇报健康。下方布局注释已据此口径更新。

```text
dopilot/                                  # 仓库根 = Docker 构建上下文（origin: senjianlu/dopilot；镜像命名空间 rabbir）
├── apps/
│   ├── server/                           # 调度中心：API、DB、APScheduler、认证、节点管理、日志聚合
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/                    # FastAPI /api/v1/* JSON + SSE 端点(server↔agent 走 Redis Streams;agent heartbeat 经此 POST 回汇报;无 WebSocket)
│   │   │   ├── redis/                      # Redis Streams 基础设施:command outbox/dispatcher、agent-events/logs consumer(见 refactor/00)
│   │   │   ├── auth/  scheduler/  nodes/  logs/  models/  repositories/  services/  config/
│   │   │   ├── executors/                 # 缝① BaseExecutor + EXECUTOR_REGISTRY
│   │   │   │   ├── base.py  scrapyd.py  script.py  docker.py
│   │   │   └── app.py
│   │   ├── migrations/  tests/  pyproject.toml
│   ├── agent/                            # worker 执行节点：主动 XREADGROUP 消费 commands，实际跑 Scrapy/Python/Docker
│   │   ├── dopilot_agent/
│   │   │   ├── api/
│   │   │   ├── redis/                     # client.py commands.py events.py logs.py：消费命令、主动 XADD 推 agent-events/logs（见 refactor/00）
│   │   │   ├── runners/                   # base.py scrapyd.py script.py docker.py
│   │   │   ├── logs/  workspace/  heartbeat/  config/  main.py    # heartbeat 经 HTTP 主动 POST /api/v1/agents/{id}/heartbeat 回 server
│   │   ├── tests/  pyproject.toml
│   └── web/                              # SPA（greenfield，直连 /api/v1）—— 〔阶段 2.1〕现为 Next.js 静态导出 + shadcn/ui + Recharts + react-i18next + TS；下方目录/文件为迁移前 Vite 布局
│       ├── src/{api,pages,components,layouts,stores,router,i18n}/  public/   # 〔阶段 2.1 后〕组件在 apps/web/components、页面在 apps/web/app
│       ├── package.json  vite.config.ts
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema（含 dopilot_protocol/streams.py：AgentCommand/AgentEvent/AgentLogEvent/AgentHeartbeat*；前端也消费可并列 protocol/typescript/）
│   └── client/                           # 可选：server→agent 客户端 SDK
├── deploy/{docker/{Dockerfile,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置（经 DOPILOT_CONFIG 加载，不继承 scrapydweb 硬编码 settings）
├── scripts/  docs/
├── reference/scrapydweb/                 # 只读行为参考，绝不进构建上下文/不被 import/不改名
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

移植核对项（在上述新骨架中实现）：

- [ ] **配置加载**：在 `apps/server/dopilot_server/config/`（及 `apps/agent/.../config/`）实现 toml 加载器，从 `configs/` 经 `DOPILOT_CONFIG` 读取；核对覆盖 scrapydweb `SCRAPYDWEB_BIND/PORT` 等配置项的**语义**（§5/§7），**不**复刻 cwd importlib 文件名形态。
- [ ] **数据模型**：在 `apps/server/dopilot_server/models/` 设计 dopilot 自有 schema；核对覆盖 scrapydweb apscheduler/timertasks/metadata/jobs 四类数据的**划分语义**（§7.1），库名/表名 dopilot 自定。
- [ ] **平台单例状态**：以稳定主键存储等价"单例状态"，版本迁移用 UPDATE，规避 §6 的版本号绑定陷阱。
- [ ] **调度**：在 `apps/server/dopilot_server/scheduler/` 实现，行为以 scrapydweb APScheduler 用法为参考（注意单实例无分布式锁的约束，见 CLAUDE.md）。
- [ ] **执行器**：在 `apps/server/dopilot_server/executors/`（`base.py`/`scrapyd.py`/`script.py`/`docker.py`，缝① BaseExecutor + 注册表）与 `apps/agent/.../runners/` 实现；行为参考 scrapydweb 对应路径。缝① 的 server↔agent 协作由 Redis Streams 承载：`run_on_node` 改为向 `dopilot:agent:{agent_id}:commands` XADD `run` 命令（经 command_outbox 事务性投递），`get_status` 改为消费 `dopilot:server:agent-events`，不再走 HTTP `/run` + 轮询 `/status`（见 `refactor/00`）。
- [ ] **Redis 通信总线**：在 `apps/server/dopilot_server/redis/` 与 `apps/agent/dopilot_agent/redis/` 实现 command outbox/dispatcher、event/log consumer（server 侧）与 command consumer、event/log publisher（agent 侧）；heartbeat 经 HTTP `POST /api/v1/agents/{agent_id}/heartbeat`，节点健康判断由 `last_seen_at` 驱动（见 `refactor/00`）。
- [ ] **静态资源/前端**：`apps/web` SPA 用前端构建产物指纹解耦版本与物理目录（吸取 §3 教训）；无 Jinja，无埋点回传。（〔阶段 2.1〕指纹由 Next.js 静态导出承担；"Vite 指纹"为迁移前措辞。）
- [ ] **进程托管**：若 agent runner 复刻 scrapydweb 子进程父死信号行为，基础镜像须 glibc（§8）。
- [ ] **不移植**：check_update 版本统计回传（§7）、Jinja strangler 共存（§4）一律不实现。

---

## 11. 开放问题（功能层）

1. **平台单例状态的迁移语义**：dopilot 自有版本号演进时，等价 scrapydweb `Metadata` 单例的存储如何做版本迁移（UPDATE 既有单例而非新建），保证管理员凭据/调度器状态/分页偏好等不丢失？（参考 §6）
2. **数据模型/共库 schema 隔离**：dopilot 沿用 scrapydweb"按 apscheduler/timertasks/metadata/jobs 四类划分数据"的语义时，若未来与其它系统共享数据库实例，是否需要在库名之外再加 schema/前缀隔离？（参考 §7.1）
3. **跨进程数据流的等价表达**：scrapydweb 用 `URL_SCRAPYDWEB` 等键在 poll/execute_task 间传递；dopilot server↔agent 的对应数据流改由 **Redis Streams 三流**（commands/agent-events/logs）+ HTTP heartbeat 承载，字段由 `packages/protocol/dopilot_protocol/streams.py`（`AgentCommand`/`AgentEvent`/`AgentLogEvent`/`AgentHeartbeat*`）的共享 schema 表达，需确认协议字段覆盖等价语义（权威设计见 `refactor/00-redis-streams-agent-communication.md`）。
4. **静态资源版本解耦的落地**：`apps/web` 的前端构建产物指纹方案如何与后端版本/缓存策略协同（参考 §3、`06-frontend-rewrite.md`）。（〔阶段 2.1〕指纹由 Next.js 静态导出承担；"Vite 构建指纹"为迁移前措辞。）
