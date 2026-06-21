# 改造分析：国际化 i18n（当前中文）

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> 适用范围：本文聚焦 **B-5「多语言 i18n：预留国际化框架，当前只需支持中文」** 的需求落地。〔阶段 2.1 起：前端改为 Next.js 静态导出 + shadcn/ui + TS，i18n 改用 **react-i18next**（`apps/web/lib/i18n/locales/{zh,en}.ts`，插值 `{{var}}`）；下文出现的 Vue 3 / Element Plus / Vite / vue-i18n 均为历史设计描述。〕下文凡引用 scrapydweb `file:line` 的内容，**仅为理解其界面文案规模/分布的行为参考**，不是 dopilot 的改动目标。
>
> 阅读约定：
> - **【scrapydweb 行为参考】**：已逐一 Read/Grep 核实的 scrapydweb 代码事实，标注 `file:line`（路径相对 `reference/scrapydweb/`），仅供理解其文案体量与分布。
> - **【dopilot 设计】 / 【开放问题】**：dopilot greenfield 的落地方案与待决策项，与上面的参考事实严格区分。

> **⚠️【历史文档 —— 阶段 2.1 已迁移前端技术栈】** 本文部分内容按**阶段 2.1 之前**的原始前端设计（**Vue 3 + Element Plus + Vite + vue-i18n + Pinia**）撰写，仅作历史/需求参考保留，**不再代表当前实现**。当前前端 i18n 为 **react-i18next**（单实例、默认中文、`apps/web/lib/i18n/locales/{zh,en}.ts`，插值 `{{var}}`），整体技术栈为 **Next.js（静态导出）+ shadcn/ui + Recharts + react-i18next + TypeScript**，纯静态产物由 dopilot-server 托管。权威说明见 `docs/dopilot/06-frontend-rewrite.md` 顶部对照表与 `docs/phases/phase-2.1/01-claude-implementation-report.md`。下文涉及 i18n 框架、前端目录路径、开发服务器、部署与静态资源策略的旧指引，一律以阶段 2.1 为准。

---

## 0. 结论速览（TL;DR）

| 维度 | dopilot 设计 | scrapydweb 行为参考（仅供理解文案体量） |
| --- | --- | --- |
| i18n 框架 | 〔阶段 2.1〕apps/web 用 **react-i18next**（单实例，默认中文，运行时可切语言）；旧设计为 vue-i18n + Element Plus 内置 locale | scrapydweb 无任何 i18n 框架（无 Flask-Babel/Babel/gettext），文案全硬编码英文 |
| 文案载体 | 〔阶段 2.1〕React 组件 / TS 通过 `t()` 取 key，译文集中在 `apps/web/lib/i18n/locales/`（插值 `{{var}}`）；旧设计为 Vue SFC + `apps/web/src/i18n/locales/` | scrapydweb 文案散落在约 37 个 Jinja 模板 + views 的 flash + 内联 JS |
| 默认语言 | 〔阶段 2.1〕`apps/web/lib/i18n` 默认 `zh`，预留 `en`；旧设计为 `apps/web/src/i18n` | scrapydweb 无语言配置项 |
| 后端文案 | `/api/v1` 仅返回结构化 `code` / 字段 / `message_key`；用户可见文案由前端按 key 本地化 | scrapydweb 服务端直接 `flash()` 英文字面量 |
| 时区等 | 如需后端感知，落在 `configs/server.example.toml`，经 dopilot toml 加载器读取 | scrapydweb 用 `default_settings.py` 硬编码 settings |

> scrapydweb 的界面文案大致分布：约 37 个 HTML 模板、views 下约 37 处服务端操作结果/错误提示、内联 JS 约 31 处 `alert()` 交互提示。这些数字是 dopilot SPA 重建导航与页面时「需要哪些文案 key、优先级如何」的清单参考，**不是 dopilot 的改造对象**。scrapydweb 服务端模板渲染文案与客户端内联 JS 文案是割裂的两套（模板抽取覆盖不到内联 JS，这是 Jinja + 内联脚本架构的固有局限）；dopilot SPA 不存在此割裂，所有前端文案统一由 i18n 框架管理（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）。

---

## 1. scrapydweb 行为参考：它没有 i18n 机制

> dopilot 是 greenfield，不存在「打开 scrapydweb 既有 i18n 开关」一说；本节仅说明 scrapydweb 自身没有任何可参考的 i18n 实现，dopilot 的 i18n 完全在 apps/web 新建（见 §7-§9）。

### 1.1 scrapydweb 无任何 i18n 依赖与框架

【scrapydweb 行为参考】

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| `setup.py` install_requires 是否含 Babel | **否** | `setup.py:35` 起的 install_requires 列表，仅有 click/Flask/Jinja2/MarkupSafe/Werkzeug 等，无 Babel/Flask-Babel |
| 是否安装 babel | **否** | scrapydweb 运行环境无 babel 包 |
| 代码中是否有真实翻译调用 | **否** | grep `babel/gettext/{% trans %}/{{ _(` 命中全部是 `__init__`/`__repr__`/CSS `transform`/压缩 JS 库的误报 |

> 含义：scrapydweb 的界面文案全为硬编码英文，**没有可复用的 i18n 体系**。dopilot 不继承其任何 i18n 形态，而是在 apps/web 从零建立（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）。

### 1.2 可作译文素材的双语注释（仅素材，非机制）

【scrapydweb 行为参考】`default_settings.py` 中有以 `# ------------------------------ Chinese --------------------------------------` 分隔的**中英双语注释块**：

```
default_settings.py:34-37   # Scrapyd 安装/启动说明（中文）
default_settings.py:59-60   # ScrapydWeb 与 Scrapyd 同机部署说明（中文）
```

这只是**配置文件的静态文档注释**，与运行期界面无关，**不是 i18n 机制**，更**不是 dopilot 的配置形态参考**（dopilot 用 `configs/*.toml`，不继承 `default_settings.py`）。它对 dopilot 的唯一价值是：

1. 证明源码文件可正常承载 UTF-8 中文（编码无障碍）；
2. 可作为部分文案**中文译文的参考来源**，供填充中文译文文件（〔阶段 2.1〕`apps/web/lib/i18n/locales/zh.ts`；旧设计 `apps/web/src/i18n/locales/zh.ts`）时取用。

---

## 2. scrapydweb 行为参考：界面文案的分布（文案清单参考）

> dopilot 没有继承来的 Jinja 模板，也没有 `base.html` / `500.html` / flash 机制；本节把 scrapydweb 的文案分布当作 **dopilot SPA 在 `apps/web` 重建导航/页面时的文案清单与优先级参考**，不是要去改的模板。

### 2.1 文案分布在三类区域

【scrapydweb 行为参考】scrapydweb 界面文案约 **37 个 `.html` 模板**，分布在三类区域：

| 区域 | scrapydweb 模板 | 文案要点（dopilot 文案清单参考） |
| --- | --- | --- |
| 主布局（PC） | `base.html` | 首屏可见：左侧导航 14 项 + Logout（共 15 个文案 key），page title/品牌串 |
| 移动端布局 | `base_mobileui.html` | 与 PC 布局独立的一套导航/title 文案 |
| 错误页 | `500.html` | 独立的错误页文案 |

### 2.2 首屏导航文案清单（dopilot 优先级参考）

【scrapydweb 行为参考】用户首屏第一眼可见的是左侧导航：

```
Servers / Timer Tasks / Jobs / Node Reports / Deploy Project / Run Spider /
Projects / Logs / Items / Send Text / Parse Log / Settings / Mobile UI / Logout
（14 导航项 + Logout = 共 15 项）
```

> dopilot SPA 在 `apps/web` 重建对应导航/页面时，这 15 项是**最高优先级的文案 key**（用户第一眼可见），应优先填入中文译文文件（〔阶段 2.1〕`apps/web/lib/i18n/locales/zh.ts`；旧设计 `apps/web/src/i18n/locales/zh.ts`）。品牌串统一用 `dopilot`。

### 2.3 服务端 flash → dopilot 的 /api/v1 错误响应

【scrapydweb 行为参考】scrapydweb 把所有服务端 flash 消息收敛到 `base.html` 的单一渲染点（`base.html:323-329`，用 `get_flashed_messages` 遍历渲染）。

【dopilot 设计】dopilot 没有 flash 机制。scrapydweb 中那些 flash 提示，在 dopilot 对应为 **`/api/v1` 的错误响应**：后端只返回结构化 `code` / `message_key`（必要时附参数），由前端 i18n（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）按 key 本地化为中文。

---

## 3. scrapydweb 行为参考：服务端会回传哪些提示

【scrapydweb 行为参考】scrapydweb 的 views 目录下约 **37 处 `flash()` 调用**，全部硬编码英文，覆盖如下几类服务端操作结果/错误提示（作为 dopilot 后端需要返回哪些 `message_key` 的清单参考）：

| 区域（scrapydweb 文件） | 提示类别 |
| --- | --- |
| `views/overview/servers.py` | 节点/Servers 相关提示 |
| `views/files/log.py` | 日志读取相关提示（含 `'%s'` 格式化串） |
| `views/dashboard/jobs.py` | 任务（Jobs）相关提示 |
| `views/operations/deploy.py` | 部署提示 |
| `views/operations/schedule.py` | 调度提示 |
| `views/overview/tasks.py` | 定时任务提示 |
| `views/utilities/parse.py` | 日志解析提示 |
| `views/baseview.py` / `check_app_config.py` | 配置校验提示 |

【dopilot 设计】dopilot 后端在 `apps/server/dopilot_server/api/v1` 全新编写，返回 JSON，不用 Flask flash、不继承 scrapydweb 的 views 划分与 gettext 包裹写法。上述约 37 类提示，在 dopilot 对应为 api/v1 的 service/handler 返回**结构化 `message_key` + 参数**，由前端 i18n（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）渲染中文。

行为层约束（对 dopilot 前端 i18n 同样适用，保留为实现注意）：
- 含 `%s` 的格式化提示串，**中文语序常需与英文不同**，应使用**具名占位符**（〔阶段 2.1〕react-i18next 的 `{{name}}` 插值；旧设计 vue-i18n 的 `{name}`），而非依赖位置顺序。
- 【dopilot 设计】`logger` 日志串**保留英文**（便于排障/搜索），仅本地化用户可见的 UI 与 api/v1 提示。

---

## 4. scrapydweb 行为参考：客户端交互提示（与服务端文案割裂）

【scrapydweb 行为参考】scrapydweb 模板内联 `<script>` 中约 **31 处 `alert()`** 外加大量 `handleMessage` 交互提示串，硬编码英文，主要分布：

| 模板 | 大致 alert 数量 |
| --- | --- |
| `schedule.html` | 11（最多） |
| `base.html` | 8 |
| `servers.html` | 4 |
| `deploy.html` | 4 |
| 其他 | 若干 |

【scrapydweb 行为参考·架构局限】这些文案在浏览器端由 JS 执行，**不经过 Jinja 渲染**——所以 scrapydweb 的「服务端模板渲染文案」与「客户端 JS 交互文案」是**割裂的两套**：服务端模板抽取覆盖不到内联 JS。这是 Jinja + 内联脚本架构的固有问题。

【dopilot 设计】dopilot SPA **不存在此割裂**：没有内联 Jinja JS、没有 `context_processor`，也就不存在「模板抽取覆盖不到 JS」这个问题。所有前端交互文案（确认删除、请至少选择一个节点等）天然由 **i18n 框架统一管理**（〔阶段 2.1〕react-i18next；旧设计 vue-i18n），与页面文案同一套 `t()` 体系、同一份 `locales/`。

> scrapydweb 这约 31 处 `alert` / `handleMessage` 文案，对 dopilot 的价值是**前端交互提示的清单参考**（dopilot 需要哪些确认/校验类提示 key），不是要去移植的方案。

---

## 5. （已删除）scrapydweb 的自定义 Jinja 定界符与 dopilot 无关

scrapydweb 在 `__init__.py:100-101` 修改了 Jinja 变量定界符（改成带空格的 `'{{ '` / `' }}'`），这是其 Jinja 模板系统的**实现细节**。dopilot 是 SPA（〔阶段 2.1〕Next.js 静态导出；旧设计 Vue），无 Jinja、无此定界符约定，相关的 `{% trans %}` / `{{ _() }}` 写法约束与 code review 规则对 dopilot **不适用**，故不展开。

---

## 6. dopilot 的 i18n 挂载点（greenfield）

dopilot **不复用 scrapydweb 的任何代码点**（不 import、不继承其模块划分）。i18n 的挂载点全部在 dopilot 自有布局内。

> 〔阶段 2.1〕下表为旧 Vue/vue-i18n 设计的挂载点。当前 react-i18next 的实际挂载点：i18n 实例与译文在 `apps/web/lib/i18n/index.ts` 与 `apps/web/lib/i18n/locales/{zh,en}.ts`，由 React provider（`apps/web/components`/`apps/web/app` 内）注入；shadcn/ui 组件文案随业务文案一并管理，无 Element Plus `ElConfigProvider` 注入。后端文案契约不变。

| 挂载点（旧设计） | 路径（旧设计） | 用途 |
| --- | --- | --- |
| vue-i18n 实例 | `apps/web/src/i18n/index.ts` | `createI18n({ locale: 'zh', ... })` |
| 译文文件 | `apps/web/src/i18n/locales/zh.ts`（+ `en.ts` 预留） | 集中存放所有 UI / 交互 / 错误 message_key 译文 |
| 应用注册 | `apps/web/src/main.ts` | `app.use(i18n)` |
| Element Plus locale | `<ElConfigProvider :locale>` | 注入 `zh-cn` / `en` 内置 locale（分页/表格空数据等组件文案） |
| 后端文案（如需） | `apps/server/dopilot_server/api/v1` 返回 `message_key` | 前端按 key 本地化；时区/默认 locale 等如需后端感知，落 `configs/server.example.toml` |

---

## 7. dopilot 的 i18n 技术选型

【dopilot 设计】dopilot 前端 i18n 与 scrapydweb 的 Flask/Jinja 版本完全无关。

> 〔阶段 2.1〕下表为旧 Vue SPA 选型（vue-i18n + Element Plus locale）。当前选型为 **react-i18next**（Next.js + shadcn/ui 生态标准），同样满足 B-5「预留多语言框架、当前只上中文」：默认 `zh`，新增语言只需补一份 `apps/web/lib/i18n/locales/<lang>.ts`；shadcn/ui 组件无内置 locale 体系，组件文案与业务文案统一走 `t()`。

| 维度（旧设计） | 选型（旧设计） | 理由 |
| --- | --- | --- |
| 框架 | **vue-i18n** | Vue 3 生态标准 i18n 库；运行时切语言、具名插值、lazy 加载 locale 都原生支持，天然满足 B-5「预留多语言框架」 |
| 组件文案 | **Element Plus 内置 locale**（`zh-cn` / `en`） | 分页、表格空数据、日期选择器等组件文案经 `ElConfigProvider` 注入即可，无需自译 |
| 默认语言 | `apps/web/src/i18n` 默认 `zh`（〔阶段 2.1〕实为 `apps/web/lib/i18n`） | B-5 当前只需中文；`en` 作为预留 locale 文件占位 |
| 后端 | `/api/v1` 仅返回 `message_key` | 后端不持有用户可见文案；前端按 key 本地化 |

> **B-5 满足方式**：i18n 框架（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）本身就是「预留多语言框架、当前只上中文」——默认 `zh`，新增语言只需补一份 `locales/<lang>.ts`（旧设计还需在 Element Plus 注入对应 locale），无需返工。

> 说明：scrapydweb 的 Flask 栈钉死版本（Flask 2.0.0 等）与 `pkg_resources`/setuptools 等运行期注意事项，属于「移植 scrapydweb **后端行为**时的运行期约束」，记录在 `05-dev-setup-and-known-issues.md`，与 dopilot 前端 i18n 选型无关，本文不再展开。

---

## 8. 落地路径（dopilot vue-i18n）

> 〔阶段 2.1 —— 历史〕本节步骤流与 §8.1/§8.2 代码示意均为旧 Vue + vue-i18n 设计，**不代表当前实现**。当前 react-i18next 落地：在 `apps/web/lib/i18n/index.ts` 用 `i18next.init({ lng: 'zh', fallbackLng: 'zh', resources: { zh, en } })`，由 `I18nextProvider`/`react-i18next` 的 `useTranslation()` 取 `t()`，译文在 `apps/web/lib/i18n/locales/{zh,en}.ts`，插值用 `{{var}}`；无 `app.use(i18n)`、无 `ElConfigProvider`。下文仅作历史参考。

```
步骤流：

 1. apps/web 安装 vue-i18n
        │
 2. apps/web/src/i18n/index.ts: createI18n(默认 zh, fallback zh)
        │
 3. apps/web/src/i18n/locales/zh.ts（+ en.ts 预留占位）
        │
 4. apps/web/src/main.ts: app.use(i18n)
        │
 5. ElConfigProvider 注入对应 Element Plus locale（zh-cn / en）
        │
 6. 页面/组件用 t('...')；优先填首屏导航 15 项（见 §2.2）
        │
 7. (可选) apps/server api/v1 返回 message_key，前端按 key 本地化
```

### 8.1 vue-i18n 初始化（示意）

```ts
// apps/web/src/i18n/index.ts
import { createI18n } from 'vue-i18n'
import zh from './locales/zh'
import en from './locales/en'   // 预留

export const i18n = createI18n({
  legacy: false,
  locale: 'zh',                 // 默认中文（B-5）
  fallbackLocale: 'zh',
  messages: { zh, en },
})
```

```ts
// apps/web/src/main.ts
import { i18n } from './i18n'
app.use(i18n)
```

### 8.2 组件内取文案（示意）

```vue
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>
<template>
  <span>{{ t('nav.servers') }}</span>
  <!-- 具名插值：中文语序自适应 -->
  <span>{{ t('deploy.failed', { name: projectName }) }}</span>
</template>
```

```ts
// apps/web/src/main.ts  Element Plus locale
import zhCn from 'element-plus/es/locale/lang/zh-cn'
// <el-config-provider :locale="zhCn"> ... </el-config-provider>
```

---

## 9. 译文目录结构（dopilot canon 布局）

【dopilot 设计】dopilot 是 `apps/` + `packages/` 的 monorepo，仓库根没有 `scrapydweb` 作为 dopilot 源码；前端 i18n 用 TS 译文模块（〔阶段 2.1〕react-i18next；旧设计 vue-i18n），**不需要** gettext 的 `babel.cfg` / `messages.pot` / `.po` / `.mo` 抽取-编译工作流。

> 〔阶段 2.1〕当前译文目录为 `apps/web/lib/i18n/`（`index.ts` + `locales/{zh,en}.ts`）；下方树为旧 `apps/web/src/i18n/` 设计，仅作历史参考。

```text
apps/web/
└── src/
    └── i18n/
        ├── index.ts                      # createI18n(默认 zh)，注册 messages
        └── locales/
            ├── zh.ts                      # 中文译文（B-5 当前唯一必需）
            └── en.ts                      # 英文预留占位
```

权威仓库布局（节选，完整见 `05-dev-setup-and-known-issues.md` §1）：

```text
dopilot/                                  # 仓库根 = Docker 构建上下文(origin: senjianlu/dopilot;镜像命名空间 rabbir)
├── apps/
│   ├── server/                           # FastAPI 调度中心:API、PostgreSQL、APScheduler、认证、节点管理、日志聚合
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/                    # FastAPI /api/v1/* JSON + SSE 端点(server↔agent 走 Redis Streams;server→web 仍 SSE、无 WebSocket)
│   │   │   ├── auth/  scheduler/  nodes/  logs/  models/  repositories/  services/  config/
│   │   │   ├── executors/                 # 缝① BaseExecutor + EXECUTOR_REGISTRY
│   │   │   │   ├── base.py  scrapyd.py  script.py  docker.py
│   │   │   └── app.py
│   │   ├── migrations/  tests/  pyproject.toml
│   ├── agent/                            # worker 执行节点:主动 XREADGROUP 消费命令 stream,实际跑 Scrapy/Python/Docker
│   │   ├── dopilot_agent/
│   │   │   ├── api/
│   │   │   ├── redis/                     # client.py commands.py events.py logs.py(消费命令、推状态/日志)
│   │   │   ├── runners/                   # base.py scrapyd.py script.py docker.py
│   │   │   ├── logs/  workspace/  heartbeat/  config/  main.py
│   │   ├── tests/  pyproject.toml
│   └── web/                              # 〔阶段 2.1〕Next.js 静态导出 + shadcn/ui + Recharts + react-i18next + TS SPA(旧设计为 Vue3 + Element Plus + Vite)
│       ├── app/  components/  lib/i18n/locales/{zh,en}.ts  public/   # 〔阶段 2.1〕旧设计为 src/{api,pages,components,layouts,stores,router,i18n}/
│       ├── package.json  next.config.{js,ts}                          # 〔阶段 2.1〕output: export + trailingSlash(旧设计 vite.config.ts)
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema(protocol/python/;前端也消费可并列 protocol/typescript/)
│   └── client/                           # 可选:server→agent 客户端 SDK
├── deploy/{docker/{Dockerfile,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置(经 DOPILOT_CONFIG 加载,不继承 scrapydweb 硬编码 settings)
├── scripts/  docs/
├── reference/scrapydweb/                 # 只读行为参考,绝不进构建上下文/不被 import/不改名
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

### 9.1 译文维护流程（无抽取/编译步骤）

译文就是普通 TS 对象，直接编辑、随构建打包，无 `pybabel extract/init/compile`。

> 〔阶段 2.1〕当前 react-i18next 插值用 `{{var}}`（如 `'部署 {{name}} 失败'`），译文文件在 `apps/web/lib/i18n/locales/zh.ts`；下方示意为旧 vue-i18n（`{name}` 插值、`apps/web/src/i18n/...`）。

```ts
// apps/web/src/i18n/locales/zh.ts   (旧设计；阶段 2.1 实为 apps/web/lib/i18n/locales/zh.ts，插值 {{name}})
export default {
  nav: { servers: '节点', timerTasks: '定时任务', /* ... 首屏 15 项见 §2.2 */ },
  deploy: { failed: '部署 {name} 失败' },   // 具名插值，中文语序自适应
}
```

新增语言只需补一份 `locales/<lang>.ts` 并在 `index.ts` 注册（〔阶段 2.1〕react-i18next 到此为止；旧设计还需在 `ElConfigProvider` 注入对应 Element Plus locale）。

> Flask/Jinja 项目可用 Flask-Babel 的 gettext 目录（`translations/<lang>/LC_MESSAGES/*.po|.mo`）管理文案，这是其 Flask 模板抽取流程，仅供理解其文案规模；dopilot 不采用。

---

## 10. 默认中文配置

【dopilot 设计】默认语言**由前端决定**（〔阶段 2.1〕落在 `apps/web/lib/i18n`，`i18next.init({ lng: 'zh', fallbackLng: 'zh' })`；旧设计落在 `apps/web/src/i18n`）：

```ts
// apps/web/src/i18n/index.ts   (旧设计；阶段 2.1 实为 apps/web/lib/i18n/index.ts 用 i18next.init)
createI18n({ locale: 'zh', fallbackLocale: 'zh', /* ... */ })
```

如需后端感知语言/时区（例如 api/v1 返回带本地化倾向的内容、或日志时区），落在 dopilot 自有 toml 配置，经 dopilot toml 加载器（`DOPILOT_CONFIG`）读取，**不使用** scrapydweb 的 `default_settings.py` / `BABEL_*` 配置键：

```toml
# configs/server.example.toml
[i18n]
locale = "zh"            # 预留多语言；当前默认中文（B-5）
timezone = "Asia/Shanghai"
```

---

## 11. 改动文件清单（dopilot canon 路径下新建）

> 全部为 dopilot 自有路径下的**新建/编写**；**不触碰 `reference/scrapydweb/*`**（只读、不进构建、不改名）。

> 〔阶段 2.1 —— 历史〕下表为旧 Vue/vue-i18n 设计的改动清单。当前 react-i18next 的对应实现：依赖为 `react-i18next` + `i18next`（无 Element Plus locale）；i18n 实例与译文在 `apps/web/lib/i18n/index.ts` 与 `apps/web/lib/i18n/locales/{zh,en}.ts`（插值 `{{var}}`）；provider 在 `apps/web/app`/`apps/web/components` 注册（无 `main.ts`、无 `ElConfigProvider`）；页面/组件落在 `apps/web/app`/`apps/web/components`。后端 `message_key` 与 `configs` 行不变。

| 文件（旧设计） | 类型 | 改动要点 |
| --- | --- | --- |
| `apps/web/package.json` | 改 | 依赖加 `vue-i18n`（Element Plus 已含内置 locale） |
| `apps/web/src/i18n/index.ts` | **新增** | `createI18n` 默认 `zh`、`fallbackLocale: 'zh'`，注册 `messages` |
| `apps/web/src/i18n/locales/zh.ts` | **新增** | 中文译文（首屏导航 15 项 + 各页/交互/错误 key） |
| `apps/web/src/i18n/locales/en.ts` | **新增（预留）** | 英文占位，证明框架可扩展 |
| `apps/web/src/main.ts` | 改 | `app.use(i18n)`；`ElConfigProvider` 注入 Element Plus `zh-cn`/`en` locale |
| `apps/web/src/pages/**`、`components/**` | 改/新增 | 文案统一用 `t('...')`，禁止硬编码字面量 |
| `apps/server/dopilot_server/api/v1/**`（可选） | 新增 | 错误/操作结果返回结构化 `message_key` + 参数，由前端本地化 |
| `configs/server.example.toml`（可选） | 改 | `[i18n] locale`/`timezone`，如后端需感知语言 |

---

## 12. 开放问题（需决策）

| # | 问题 | 倾向/建议 |
| --- | --- | --- |
| 1 | 组件文案中文化方式 | 〔阶段 2.1〕shadcn/ui 无内置 locale 体系，组件文案与业务文案一并由 react-i18next `t()` 管理；旧设计为 Element Plus 自带 `zh-cn`/`en` locale 经 `ElConfigProvider` 注入、与 vue-i18n 协同 |
| 2 | 是否提供**语言切换 UI** | B-5 当前只要中文；i18n 框架（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）已原生支持运行时切语言，是否暴露切换器为产品决策，可后置 |
| 3 | 后端错误是否返回 `message_key` | 倾向是：api/v1 返回结构化 `code`/`message_key` + 参数，由前端 i18n（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）渲染；避免后端持有用户可见中文 |
| 4 | 日志本地化边界 | **日志保留英文**（便于排障/搜索），仅本地化用户可见 UI 与 api/v1 提示 |
| 5 | 品牌名 | dopilot 在 `apps/web` 文案/标题统一用 `dopilot`，greenfield 无 scrapydweb `base.html` 协调问题 |

---

## 13. 与 dopilot 三类调度对象的关系（提示）

【dopilot 设计】i18n 是**横切关注点**，对 Scrapy 爬虫 / Python3 脚本 / Docker 常驻爬虫三类对象的新增页面同样适用：新页面从一开始就用 `t()` 取文案（〔阶段 2.1〕react-i18next；旧设计 vue-i18n）、译文集中在前端 i18n locales（〔阶段 2.1〕`apps/web/lib/i18n/locales`；旧设计 `apps/web/src/i18n/locales`），禁止硬编码字面量，从而避免积累文案债务；后端对应的 api/v1 提示返回 `message_key`。译文集中管理意味着新增页面/语言只需补 `locales/` 条目，无需任何抽取/编译步骤。
