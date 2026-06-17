# 改造分析：国际化 i18n（当前中文）

> 适用范围：dopilot 平台基于 scrapydweb 改造。本文聚焦 **B-5「多语言 i18n：预留国际化框架，当前只需支持中文」** 的需求落地。
>
> 阅读约定：
> - **【现状事实】**：已逐一 Read/Grep 核实的代码事实，标注 `file:line`。
> - **【改造建议】 / 【开放问题】**：需要工程师决策或后续实施的内容，与事实严格区分。
> - 所有路径均为仓库内绝对/相对路径，已核对。

---

## 0. 结论速览（TL;DR）

| 维度 | 现状事实 | 推荐动作 |
| --- | --- | --- |
| i18n 框架 | **完全没有**，无 Flask-Babel / Babel / gettext，`.venv` 无 babel 包 | 引入 **Flask-Babel 2.0.0 + Babel 2.9.x**（兼容旧栈，旧式装饰器） |
| 模板文案 | 37 个 HTML 模板全部硬编码英文，`<html>` 无 `lang` 属性 | 加 `lang='zh'`，文案包 `{% trans %}` / `{{ _('...') }}` |
| Python 文案 | 37 处 `flash()` 调用硬编码英文 | 包 `gettext` / `lazy_gettext` |
| JS 内联文案 | 31 处 `alert()` 硬编码英文，模板 i18n 覆盖不到 | 后端 `context_processor` 注入中文字典，JS 按 key 取 |
| 默认语言 | 无配置项 | `default_settings.py` 新增 `LANGUAGE='zh'` |
| 推荐方案 | — | **方案 B（分阶段）+ 方案 A 的依赖选型** |

**核心陷阱（dopilot 特有）**：`scrapydweb/__init__.py:100-101` 把 Jinja **变量定界符** 改成了带空格的 `'{{ '` / `' }}'`，但 **block 定界符仍是标准 `{% %}`**。因此：
- `{% trans %}...{% endtrans %}` 块标签**可直接用**；
- `{{ _('...') }}` 内联调用**必须带空格写**，否则不渲染。

---

## 1. 现状事实：i18n 完全缺失

### 1.1 无任何 i18n 依赖与框架

【现状事实】

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| `setup.py` install_requires 是否含 Babel | **否** | `setup.py:35` 起的 install_requires 列表，仅有 click/Flask/Jinja2/MarkupSafe/Werkzeug 等，无 Babel/Flask-Babel |
| `.venv` 是否安装 babel | **否** | `ls .venv/lib/python*/site-packages/ \| grep -i babel` → 空 |
| 代码中是否有真实翻译调用 | **否** | grep `babel/gettext/{% trans %}/{{ _(` 命中全部是 `__init__`/`__repr__`/CSS `transform`/压缩 JS 库的误报 |

> 也就是说，i18n 是**从零搭建**，不存在任何可直接打开的开关。

### 1.2 唯一与「中文」相关的现状（非 i18n 机制）

【现状事实】`scrapydweb/default_settings.py` 中有以 `# ------------------------------ Chinese --------------------------------------` 分隔的**中英双语注释块**：

```
default_settings.py:34-37   # Scrapyd 安装/启动说明（中文）
default_settings.py:59-60   # ScrapydWeb 与 Scrapyd 同机部署说明（中文）
```

这只是**配置文件的静态文档注释**，与运行期界面无关，**不是 i18n 机制**。但它有两个复用价值：

1. 证明项目源码文件可正常承载 UTF-8 中文（编码无障碍）；
2. 可作为部分文案中文翻译的**参考来源**与**双语注释惯例**。

---

## 2. 现状事实：模板层文案

### 2.1 模板规模与布局

【现状事实】

- 模板总数：**37 个** `.html`（`find scrapydweb/templates -name "*.html" | wc -l`）。
- 存在**三套独立布局/头部**，都要单独处理 `lang` 与文案：

| 模板 | 角色 | 关键问题 |
| --- | --- | --- |
| `scrapydweb/templates/base.html` | 主布局（PC） | `base.html:2` 裸 `<html>`；`base.html:7` title 硬编码 `- ScrapydWeb`；左侧菜单 14 个导航项 + Logout（共 15 个 `<span>`）硬编码 |
| `scrapydweb/templates/base_mobileui.html` | 移动端独立布局 | 同样裸 `<html>`、title/导航硬编码，**独立于 base.html** |
| `scrapydweb/templates/500.html` | 错误页（不继承 base，自带 head） | 裸 `<html>` + 文案独立，**最易遗漏** |

### 2.2 base.html 硬编码文案位置

【现状事实】

```
base.html:2     <html>                         ← 缺 lang 属性
base.html:7     <title>{% block title %}{% endblock %} - ScrapydWeb</title>   ← 品牌+连接符硬编码
base.html:143   <span>Servers</span>           ← 左侧菜单（首批翻译对象）
base.html:151   <span>Timer Tasks</span>
   ...          Jobs / Node Reports / Deploy Project / Run Spider /
                Projects / Logs / Items / Send Text / Parse Log /
                Settings / Mobile UI / Logout（14 导航项 + Logout = 共 15 项）
base.html:323   {% with messages = get_flashed_messages(with_categories=true) %}
base.html:327     <li class="{{ category }}">{{ message }}</li>   ← flash 唯一渲染点
```

> 菜单文案是用户第一眼可见的内容，列为一期翻译重点。

### 2.3 flash 渲染入口（重要复用点）

【现状事实】`base.html:323-329` 是**所有 flash 文案的唯一渲染点**：

```jinja
{% with messages = get_flashed_messages(with_categories=true) %}
  <ul class="flashes">
  {% if messages %}
  {% for category, message in messages %}
    <li class="{{ category }}">{{ message }}</li>
  ...
```

【改造建议】只要在 **`flash()` 调用处**包 `gettext`，渲染端**完全无需改动** —— flash 的翻译是「源头包裹、渲染透明」。

---

## 3. 现状事实：Python 视图文案

【现状事实】views 目录下共 **37 处 `flash()` 调用**（`grep -rn "flash(" scrapydweb/views/ | wc -l`），全部硬编码英文，分布如下（行号为核实区间）：

| 文件 | 说明 |
| --- | --- |
| `scrapydweb/views/overview/servers.py` | `flash()` 串（约 32-36 行等）；模块级常量宜用 `lazy_gettext` |
| `scrapydweb/views/files/log.py` | 多处 flash（约 90-336 行），含 `'%s'` 格式化串 |
| `scrapydweb/views/dashboard/jobs.py` | `set_flash` 等多处 flash（约 143-265 行） |
| `scrapydweb/views/operations/deploy.py` | 部署提示 flash |
| `scrapydweb/views/operations/schedule.py` | 调度提示 flash |
| `scrapydweb/views/overview/tasks.py` | 定时任务 flash |
| `scrapydweb/views/utilities/parse.py` | 日志解析 flash |
| `scrapydweb/views/baseview.py` 及 `check_app_config.py` | 配置校验提示 |

【改造建议】
- 含 `'%s'` 的串改为 `gettext('... %s ...') % value` 或 `.format()`，**注意翻译串里占位符顺序要与原串一致**（中文语序常需调整，必要时用具名占位符 `{name}`）。
- **模块级/类级常量**（在请求上下文之外求值）必须用 `lazy_gettext`，否则会因无 app context 报错或不翻译。
- 【开放问题】`logger` 日志串是否翻译？建议**日志保留英文**（便于排障/搜索），仅翻译用户可见 UI 与 flash。

---

## 4. 现状事实：JS 内联文案（最大盲区）

【现状事实】模板内联 `<script>` 中共 **31 处 `alert()`**（`grep -rn "alert(" scrapydweb/templates/ | wc -l`）外加大量 `handleMessage` 提示串，硬编码英文，主要分布：

| 模板 | 大致 alert 数量 |
| --- | --- |
| `schedule.html` | 11（最多） |
| `base.html` | 8 |
| `servers.html` | 4 |
| `deploy.html` | 4 |
| 其他 | 若干 |

【现状事实】这些文案在浏览器端由 JS 执行，**不经过 Jinja 渲染**，因此 `{% trans %}` / `{{ _() }}` 的模板抽取**覆盖不到**。这是 i18n 的最大盲区。

```
模板 i18n 覆盖范围示意：

  Jinja 渲染期（服务端）          浏览器执行期（客户端）
  ┌───────────────────┐         ┌──────────────────────┐
  │ {% trans %}...     │         │ alert("Are you ...")  │  ← 覆盖不到！
  │ {{ _('Servers') }} │  ✅     │ handleMessage("...")  │  ← 覆盖不到！
  │ flash 渲染 (透明)   │         │                      │
  └───────────────────┘         └──────────────────────┘
            │                              ▲
            │  context_processor 注入       │
            └──── JS_I18N 中文字典 ─────────┘ （推荐方案）
```

【改造建议（推荐）】由后端 `context_processor` 注入一份 JS 中文文案字典，JS 中按 key 取值：

```python
# __init__.py  inject_variable() 内追加
JS_I18N=dict(
    confirm_delete=gettext('确定要删除吗？'),
    select_at_least_one_node=gettext('请至少选择一个节点'),
    ...
)
```
```javascript
// 模板内联 JS
alert(JS_I18N.confirm_delete);
```

【开放问题】JS 文案策略二选一：
- **A. context_processor 注入字典**（集中、复用 gettext 翻译目录）——推荐；
- **B. 为 JS 单独建一份独立中文常量文件**（解耦，但翻译分散两套）。

---

## 5. 关键约束：自定义 Jinja 变量定界符

【现状事实】`scrapydweb/__init__.py:100-101`：

```python
app.jinja_env.variable_start_string = '{{ '
app.jinja_env.variable_end_string = ' }}'
```

- **只改了 variable 定界符**（带前后空格），**未改 block 定界符**（仍是标准 `{% %}`）。

【改造影响】

| 语法 | 是否可用 | 写法要求 |
| --- | --- | --- |
| `{% trans %}文本{% endtrans %}` | ✅ 可直接用 | block 定界符未变 |
| `{{ _('文本') }}` 内联 | ✅ 可用 | **必须带空格**：`{{ _('...') }}`，不可写 `{{_('...')}}` |
| `{{_('...')}}`（无空格） | ❌ 不渲染 | 违反定界符约定 |

【改造建议】团队约定：**优先用 `{% trans %}` 块标签**（不受定界符空格陷阱影响、可读性好）；确需内联时严格遵守带空格写法，并在 code review 检查表中列入此条。

---

## 6. 可复用的现成挂载点

【现状事实】下表是 scrapydweb 已有、可直接承载 i18n 初始化的代码点：

| 复用点 | 文件:行 | 用途 |
| --- | --- | --- |
| `Compress.init_app` 旁 | `__init__.py:103-104` | Flask 扩展注册的现成位置，`babel.init_app(app)` 直接加此处 |
| `jinja_env` 定制区 | `__init__.py:97-101` | 配置 babel jinja 扩展 / 默认 locale 的天然落点 |
| `inject_variable` context_processor | `__init__.py:306-347` | 已向所有模板注入全局变量，可追加 `CURRENT_LOCALE`/`LANGUAGE`/`JS_I18N` |
| `BaseView.__init__` 配置读取层 | `views/baseview.py` | 把 `app.config` 逐项读到 `self.*`，新增 `LANGUAGE`/`DEFAULT_LOCALE` 的统一消费入口 |
| flash 唯一渲染点 | `base.html:323-329` | 源头包 gettext 后渲染端透明，无需改 |
| block 定界符保持标准 | `__init__.py:100-101` | `{% trans %}` 可直接用 |
| 双语注释惯例 | `default_settings.py:34-37` 等 | 中文翻译参考来源 + 编码验证 |

---

## 7. 方案对比与推荐

### 7.1 候选方案

| 方案 | 做法 | 优点 | 缺点 | 工作量 |
| --- | --- | --- | --- | --- |
| **A. Flask-Babel 2.0.0 全量** | 引入 Flask-Babel 2.0.0 + Babel 2.9.x，create_app 初始化，`{% trans %}`/`{{ _() }}`/`gettext` 全量抽取，建 pot/po/mo | 标准、可扩展，真正「预留多语言框架」；与旧栈兼容（旧式装饰器） | 工作量大；新增构建步骤；JS 仍需单独通道 | 高（2-4 人日） |
| **B. 分阶段（推荐）** | 一期：接框架 + locale_selector + `<html lang>` + base 导航/title + 高频 flash + pot/po/mo；后续逐页增量 | 快速产出可见中文（导航优先）；框架一次到位；可并行翻译 | 过渡期中英混排；需 backlog 跟踪剩余文案 | 中（一期 1-1.5 人日） |
| **C. 仅硬替换中文（不引框架）** | 直接把英文串改中文字面量 | 改动直接、零依赖、无版本风险 | **违背 B-5「预留多语言框架」**，无法切换语言、未来加语言要返工 | 中（无框架价值） |
| **D. 升级 Flask 栈 + Flask-Babel 4.x** | 解钉 Flask>=2.2，用新式 `locale_selector=` API | 用最新 API、长期维护好 | 牵动 models/bootstrap 旧版依赖耦合（`db.app=app` 在 Flask-SQLAlchemy 3.x 失效，见 `__init__.py:123`），风险外溢 | 很高（框架升级+回归） |

### 7.2 推荐：方案 B（分阶段）+ 方案 A 的依赖选型

> **B-5 明确要求「预留多语言框架、当前只需中文」**，故必须引入真正的 i18n 框架（**排除 C**）；但不应为此升级整个 Flask 栈（**排除 D**，避免与 models/bootstrap 子系统已知的旧版依赖耦合冲突）。

**依赖选型（关键）**：

| 包 | 版本 | 理由 |
| --- | --- | --- |
| Flask-Babel | **2.0.0** | 用**旧式 `@babel.localeselector` 装饰器**，**不要求 Flask>=2.2**，与钉死的 Flask 2.0.0 兼容；Flask-Babel 4.x 的新式 `locale_selector=` 参数要求 Flask>=2.2，会触发框架升级 |
| Babel | **2.9.1（2.9.x）** | 与 click 7.1.2 / Jinja2 3.0.0 / MarkupSafe 2.0.0 兼容 |

【现状事实·钉死的版本】`setup.py`：

```
click==7.1.2      (setup.py:37)
Flask==2.0.0      (setup.py:39)
Jinja2==3.0.0     (setup.py:44)
MarkupSafe==2.0.0 (setup.py:46)
Werkzeug==2.0.0   (setup.py:56)
```

---

## 8. 落地路径（推荐方案 B 的实施步骤）

```
步骤流（一期）：

 1. setup.py 加依赖 + package_data
        │
 2. __init__.py: babel.init_app + @babel.localeselector(默认 zh)
        │
 3. default_settings.py: LANGUAGE='zh' (+ BABEL_DEFAULT_*)
        │
 4. baseview.py: self.LANGUAGE = app.config.get('LANGUAGE','zh')
        │
 5. 建 babel.cfg → pybabel extract → init -l zh → 翻译 → compile
        │
 6. 一期翻译: base.html 导航/title + <html lang='zh'> + 高频 flash
        │
 7. JS 文案: context_processor 注入 JS_I18N 字典
        │
 8. 后续: 逐页 / 移动端 / 500.html / 剩余 flash 增量补 po 条目
```

### 8.1 create_app 初始化（示意）

```python
# __init__.py，紧邻 compress.init_app(app)（约 103-104 行）
from flask_babel import Babel
babel = Babel()
babel.init_app(app)

@babel.localeselector            # Flask-Babel 2.0.0 旧式装饰器
def get_locale():
    # 预留：可从 session / Accept-Language 读取
    return app.config.get('LANGUAGE', 'zh')
```

### 8.2 模板抽取写法

```jinja
<!-- 推荐：块标签（不受定界符空格陷阱影响） -->
<span>{% trans %}Servers{% endtrans %}</span>
<title>{% block title %}{% endblock %} - {{ _('dopilot') }}</title>
<html lang="{{ CURRENT_LOCALE }}">     <!-- 注意带空格内联写法 -->
```

---

## 9. 翻译目录结构与抽取流程

### 9.1 目标目录结构（新增）

```
dopilot/
├── babel.cfg                              ← 新增，提取配置
├── messages.pot                           ← 生成（提取产物，可不入库）
├── setup.py                               ← 改：依赖 + package_data
└── scrapydweb/
    ├── __init__.py                        ← 改：babel.init_app + localeselector + JS_I18N
    ├── default_settings.py                ← 改：LANGUAGE='zh'
    ├── views/baseview.py                  ← 改：读 self.LANGUAGE
    └── translations/                      ← 新增（整个目录）
        └── zh/
            └── LC_MESSAGES/
                ├── messages.po            ← 翻译源（人工编辑）
                └── messages.mo            ← 编译产物（随包分发）
```

### 9.2 babel.cfg（新增）

```ini
[python: scrapydweb/**.py]

[jinja2: scrapydweb/templates/**.html]
extensions=jinja2.ext.i18n
# 关键：自定义带空格变量定界符需声明，否则 {{ _() }} 可能抽取不到
variable_start_string = {{ 
variable_end_string =  }}
```

【开放问题】上述 `variable_start_string` 声明能否让 `pybabel extract` 在**带空格定界符**下正确抓到 `{{ _() }}` 调用，**需实测**；若不行，则一期内联翻译统一改用 `{% trans %}` 块标签（block 定界符是标准的，提取无障碍）。

### 9.3 抽取-翻译-编译流程

```bash
# 1. 提取所有 gettext 调用到 messages.pot
pybabel extract -F babel.cfg -o messages.pot .

# 2. 初始化中文 catalog（仅首次）
pybabel init -i messages.pot -d scrapydweb/translations -l zh

# 3. 人工翻译 scrapydweb/translations/zh/LC_MESSAGES/messages.po

# 4. 编译为 .mo（运行期加载）
pybabel compile -d scrapydweb/translations

# 后续源码新增文案后，用 update 合并（保留已有翻译）：
pybabel update -i messages.pot -d scrapydweb/translations
```

---

## 10. 默认中文配置

【改造建议】`scrapydweb/default_settings.py` 新增（配套中英双语注释，沿用现有惯例）：

```python
# ------------------------------ Chinese --------------------------------------
# 界面语言，当前仅支持 'zh'（中文）。预留多语言框架，未来可加 'en' 等。
# Interface language. Currently only 'zh' is supported.
LANGUAGE = 'zh'
BABEL_DEFAULT_LOCALE = 'zh'
BABEL_DEFAULT_TIMEZONE = 'Asia/Shanghai'
```

- `LANGUAGE` 由 `BaseView.__init__` 读入 `self.LANGUAGE`，并作为 `localeselector` 默认返回值。
- `BABEL_DEFAULT_LOCALE` 是 Flask-Babel 在 selector 返回空时的兜底。

---

## 11. 改动文件清单

| 文件 | 类型 | 改动要点 |
| --- | --- | --- |
| `setup.py` | 改 | install_requires 加 `Flask-Babel==2.0.0`、`Babel==2.9.1`；package_data 加 `translations/*/LC_MESSAGES/*.mo`（及 `.po`） |
| `scrapydweb/__init__.py` | 改 | 103-104 行旁 `babel.init_app(app)` + `@babel.localeselector`（默认 zh）；`inject_variable`（306-347）追加 `CURRENT_LOCALE`/`LANGUAGE`/`JS_I18N`；保留 100-101 带空格定界符 |
| `scrapydweb/default_settings.py` | 改 | 新增 `LANGUAGE='zh'` + `BABEL_DEFAULT_LOCALE`/`BABEL_DEFAULT_TIMEZONE` + 双语注释 |
| `scrapydweb/views/baseview.py` | 改 | `self.LANGUAGE = app.config.get('LANGUAGE', 'zh')` |
| `scrapydweb/templates/base.html` | 改 | `<html lang>`（2 行）；title（7 行）；15 项菜单 `<span>`（14 导航 + Logout，143 行起）；flash 渲染处（323）无需改 |
| `scrapydweb/templates/base_mobileui.html` | 改 | 独立布局，同样加 `lang` + title/导航翻译标记 |
| `scrapydweb/templates/500.html` | 改 | 不继承 base、自带 head，独立加 `lang` + 文案翻译（易遗漏） |
| `scrapydweb/views/overview/servers.py` | 改 | flash 包 gettext（模块级常量用 lazy_gettext） |
| `scrapydweb/views/files/log.py` | 改 | 多处 flash（含 `'%s'`）包 gettext，保留占位符 |
| `scrapydweb/views/dashboard/jobs.py` | 改 | `set_flash` 等多处 flash 包 gettext |
| `scrapydweb/views/operations/deploy.py` / `schedule.py` | 改 | flash/提示包 gettext |
| `scrapydweb/views/overview/tasks.py` | 改 | flash 包 gettext |
| `scrapydweb/views/utilities/parse.py` | 改 | flash 包 gettext |
| `scrapydweb/templates/scrapydweb/*.html` | 改 | 逐页文案包 `{{ _() }}`/`{% trans %}`；内联 `<script>` 的 alert/提示改引用 `JS_I18N`（31 处 alert） |
| `babel.cfg` | **新增** | python + jinja2 提取配置（声明自定义定界符） |
| `scrapydweb/translations/zh/LC_MESSAGES/messages.po` `.mo` | **新增** | pybabel extract/init/compile 产物，中文翻译目录 |

---

## 12. 开放问题（需决策）

| # | 问题 | 倾向/建议 |
| --- | --- | --- |
| 1 | Flask-Babel/Babel 与钉死的 Flask 2.0.0/click 7.1.2/Jinja2 3.0.0/MarkupSafe 2.0.0 **精确兼容版本** | 建议 Flask-Babel 2.0.0 + Babel 2.9.1；**需在 `.venv` 实测安装与运行**（旧式 `@babel.localeselector` 是否可用、是否触发 click/Jinja 版本冲突） |
| 2 | JS 内联文案（31 alert + handleMessage）中文化策略 | 推荐 A：context_processor 注入字典；B：JS 单独常量文件 |
| 3 | `babel.cfg` jinja2 提取器在**带空格定界符**下能否抓到 `{{ _() }}` | 需 `pybabel extract` 实测；不行则一期统一用 `{% trans %}` 块标签 |
| 4 | Vue + Element-UI 页面（`schedule.html`/`tasks.html`/`servers.html`）的组件文案与 **Element-UI 内置英文**（分页/表格空数据等）是否中文化 | Element-UI 有自带 `zh-CN` locale 包，需决定是否引入 |
| 5 | 是否需要**语言切换 UI** | B-5 当前只要中文；建议一期仅靠 `LANGUAGE` 配置/Accept-Language，UI 暂不加切换器（框架已预留 selector） |
| 6 | 翻译范围边界：是否翻译 `default_settings.py` 注释、`settings.html` 配置说明、logger 日志 | 建议**日志保留英文**，仅翻译用户可见 UI 与 flash |
| 7 | **品牌改名（ScrapydWeb→dopilot）与 i18n 是否合并处理** | title/菜单/品牌串与翻译都在 `base.html` 同一区域，**需与 B 品牌改造任务协调**，避免重复改动 `base.html` |

---

## 13. 与 dopilot 三类调度对象的关系（提示）

【改造建议】i18n 框架是**横切关注点**，对 Scrapy 爬虫 / Docker 常驻爬虫 / Python3 脚本三类对象的新增页面同样适用：新页面从一开始就用 `{% trans %}` 与 `gettext` 编写，避免再次积累英文硬编码债务；新视图的 flash 一律包 gettext。本文建立的 babel.cfg / translations 目录会自动覆盖后续新增的模板与视图（只要符合 `babel.cfg` 的扫描路径 `scrapydweb/**.py` 与 `scrapydweb/templates/**.html`）。
