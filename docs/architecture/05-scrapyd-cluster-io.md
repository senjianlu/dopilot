# 05 · Scrapyd 集群通信

> **【scrapydweb 行为参考·边界】** 本文描述 **scrapydweb 现状行为/语义**，作为 dopilot 的**功能层参考**；其代码写法、目录结构、模块划分**不得作为 dopilot 设计依据**。文中 `file:line` 路径均**相对 `reference/scrapydweb/`**（如 `scrapydweb/run.py` 即 `reference/scrapydweb/scrapydweb/run.py`；该目录只读、不被 import、不参与构建、不改名）。任何“改造切入点/复用/保留”类措辞，一律理解为“dopilot 需在 `apps/` 下**全新复刻其行为语义**”，而非改动或照搬 scrapydweb 文件。详见 `../dopilot/00-requirements.md` 决策表。
>
> 本文面向参与 dopilot 改造的工程师，剖析 scrapydweb 与多个 scrapyd 节点之间的通信层：节点寻址、单节点 JSON API 调用封装、多节点 fan-out 与响应聚合、超时/错误/认证处理，以及 logparser 日志解析与统计流程。最后说明这一层与 dopilot 新执行器（Docker 常驻爬虫 / Python3 脚本）的关系。
>
> 文中区分两类内容：
> - **【现状】** 当前代码事实，均标注真实文件路径与 `file:line`；
> - **【改造】 / 【开放问题】** 针对 dopilot 目标的建议与待决策点，属于设计意见而非既有实现。
>
> 关联文档：`01-bootstrap-and-config.md`（配置解析）、`03-scheduler-engine.md`（定时引擎）、`02-data-model.md`（Task/TaskResult 模型）。

---

## 1. 一句话定位

**scrapydweb 没有真正的服务端多节点并发聚合层。** 每一次进程内的 scrapyd HTTP 调用都只面向**单个 node**，由 `BaseView.make_request()` 统一封装认证/超时/错误。所谓「对所有节点执行并汇总」绝大多数是在**浏览器端用 JavaScript 逐节点发 XHR** 实现的（前端 fan-out，DOM 聚合）。唯一在**服务端**做多节点串行下发的是定时任务执行器 `TaskExecutor`（见 `03-scheduler-engine.md`）。

```
                       ┌───────────────────────────────────────────────┐
                       │              scrapydweb 进程                     │
                       │                                                │
  浏览器  ─XHR(/N/..)─▶ │  Flask 路由 /<int:node>/...                      │
   │  (前端 fan-out)    │      │                                          │
   │                   │      ▼                                          │
   │                   │  BaseView.__init__  ──node-1──▶ 4 个并行 list    │
   │                   │      │             (SERVERS/GROUPS/AUTHS/URLS)   │
   │                   │      ▼                                          │
   │                   │  ApiView (API_MAP) ─▶ make_request() ──┐        │
   │                   │                       (全局 session)    │        │
   │  ◀── JSON ─────────┤                                       │        │
   │                   └───────────────────────────────────────┼────────┘
   │                                                            │ 单节点一次 HTTP
   │                                                            ▼
   │                                            ┌──────────────────────────┐
   └──对每个被选 node 重复───────────────────────▶│ scrapyd 节点 host:port    │
                                                │  /schedule.json /cancel… │
                                                │  + logparser daemon      │
                                                │    解析 *.log → *.json    │
                                                └──────────────────────────┘
```

---

## 2. 关键文件总览

| 文件 | 角色 |
| --- | --- |
| `scrapydweb/views/baseview.py` | 所有视图基类。`__init__` 用 URL 的 `node` 从配置取出该节点的 server/auth/group/public_url；`make_request()` 是**唯一**的 scrapyd HTTP 调用封装；`get_selected_nodes()` 读勾选节点；`get_response_from_view()` 进程内自调用 |
| `scrapydweb/views/api.py` | scrapyd JSON API 抽象层。`ApiView` 用 `API_MAP` 把语义 opt 翻译成 scrapyd 端点，构造 URL/data、调 `make_request`、在 `handle_result` 附加用户提示 |
| `scrapydweb/views/overview/multinode.py` | 多节点写操作（stop/delversion/delproject）入口。**自身不发请求**，只渲染模板把节点列表 + 单节点 ApiView URL 交给前端 |
| `scrapydweb/templates/scrapydweb/multinode_results.html` | 客户端 fan-out 的真正实现。`fireXHR()`/`execXHR()` 逐节点替换 URL 节点号并发 XHR，把响应写入对应表格行（**聚合发生在 DOM**） |
| `scrapydweb/views/operations/schedule.py` | 立即运行/定时任务核心。`ScheduleRunView` 仅同步向**首个被选节点**发 `schedule.json`，其余交前端 `schedule.xhr` 补发 |
| `scrapydweb/views/operations/execute_task.py` | 定时任务执行器。`TaskExecutor.main` 串行遍历 `selected_nodes`，用 `get_response_from_view` 进程内自调 `/N/schedule/task/`，失败重试一次（**服务端真正的多节点下发**） |
| `scrapydweb/utils/poll.py` | 独立子进程。周期 GET 每个 scrapyd 的 `/jobs` HTML（正则解析任务），再反向 POST scrapydweb 自身 `/N/log/stats/` 触发统计与告警 |
| `scrapydweb/views/files/log.py` | 日志与统计页。`LogView` 优先 logparser：本地 `.json` → 远程 `.json` → 备份 → 兜底 `parse()` 整段日志；负责刷新、备份、监控告警 |
| `scrapydweb/utils/check_app_config.py` | 启动期把 `SCRAPYD_SERVERS` 配置解析成 4 个并行列表，并逐节点 GET 做连通性检查 |
| `scrapydweb/common.py` | 共享底层：全局 `requests.Session`（连接池 1000）、`get_response_from_view`、`basic_auth_header`、metadata、`json_dumps` |
| `scrapydweb/__init__.py` | 路由注册。`register_view` 给所有视图加 `/<int:node>/` 前缀，使 node 成为强制路由参数 |

---

## 3. 节点寻址：node 索引模型

### 3.1【现状】所有 scrapyd 操作 URL 都以 `/<int:node>/` 开头

路由注册时由 `register_view` 统一加前缀，`scrapydweb/__init__.py:148-159`：

```python
def register_view(view, endpoint, url_defaults_list, with_node=True, trailing_slash=True):
    ...
    rule = '/<int:node>/%s' % url if with_node else '/%s' % url
    ...
    if not with_node:
        ...
        defaults = dict(node=1)          # 无 node 的端点（如 sendtext）默认补 node=1
```

`ApiView` 注册了三种 URL 形态（`scrapydweb/__init__.py:166-171`），全部带 node：

```python
register_view(ApiView, 'api', [
    ('api/<opt>/<project>/<version_spider_job>', None),
    ('api/<opt>/<project>', dict(version_spider_job=None)),
    ('api/<opt>', dict(project=None, version_spider_job=None))
])
```

### 3.2【现状】node 是 1-based 整数，索引 4 个并行列表

`BaseView.__init__` 解析 node 并取出该节点的全部元数据，`scrapydweb/views/baseview.py:189-197`：

```python
self.node = self.view_args['node']
assert 0 < self.node <= self.SCRAPYD_SERVERS_AMOUNT, \
    'node index error: %s, which should be between 1 and %s' % (self.node, self.SCRAPYD_SERVERS_AMOUNT)
self.SCRAPYD_SERVER = self.SCRAPYD_SERVERS[self.node - 1]
self.IS_LOCAL_SCRAPYD_SERVER = self.SCRAPYD_SERVER == self.LOCAL_SCRAPYD_SERVER
self.GROUP = self.SCRAPYD_SERVERS_GROUPS[self.node - 1]
self.AUTH = self.SCRAPYD_SERVERS_AUTHS[self.node - 1]
self.SCRAPYD_SERVER_PUBLIC_URL = self.SCRAPYD_SERVERS_PUBLIC_URLS[self.node - 1]
```

「指定节点」就是通过 URL 里的 node 索引实现的。四个列表的来源见 §4。

```
node (URL 第一段)  ──减 1──▶  下标
   1   ─▶ idx 0  ─▶  SCRAPYD_SERVERS[0]      = "10.0.0.1:6800"
                     SCRAPYD_SERVERS_GROUPS[0]  = "groupA"
                     SCRAPYD_SERVERS_AUTHS[0]   = ("user","pass") | None
                     SCRAPYD_SERVERS_PUBLIC_URLS[0] = "http://..." | ""
   2   ─▶ idx 1  ─▶  ...
```

### 3.3【陷阱】node 编号会随节点增删而漂移

`check_scrapyd_servers` 对节点做了 `sorted(set(...))` 重排（`scrapydweb/utils/check_app_config.py:388`），排序键是 `[group, ip, port]`（`check_app_config.py:382-386`）。因此 **node 编号对应的是排序后的顺序，不是配置文件里的书写顺序**。增删任意一个节点都可能让其它节点的 node 编号变化，而 `Task.selected_nodes` 以整数列表的形式存进 DB（见 §6），**历史任务可能因此指向错节点**。

> 【开放问题】dopilot 引入更多节点类型后，节点数量与种类都会增加，这个「按 ip/port 排序 + 整数下标」的寻址模型脆弱性会被放大。建议改为稳定主键（DB 自增 id 或 UUID），详见 §9.5。

---

## 4. 配置解析：从字符串到 4 个并行列表

### 4.1【现状】启动期把 `SCRAPYD_SERVERS` 拆成 4 个等长列表

`check_scrapyd_servers`（`scrapydweb/utils/check_app_config.py:360-395`）：

- 每项可以是字符串 `'usr:psw@ip:port#group'`（经 `SCRAPYD_SERVER_PATTERN` 正则，`check_app_config.py:25-35`）或 5 元组 `(usr, psw, ip, port, group)`；
- 缺省值：ip → `127.0.0.1`，port → `6800`，group → `''`；
- auth 规则：`auth = (usr, psw) if usr and psw else None`（`check_app_config.py:378`）；
- `sorted(set(servers), key=key_func)` 去重 + 排序；
- 最终写回 config 的 4 个列表（`check_app_config.py:392-395`）：

```python
config['SCRAPYD_SERVERS']             = ['%s:%s' % (ip, port) for ...]   # 注意：丢弃了 auth/group
config['SCRAPYD_SERVERS_GROUPS']      = [group for ...]
config['SCRAPYD_SERVERS_AUTHS']       = [auth for ...]
config['SCRAPYD_SERVERS_PUBLIC_URLS'] = [public_url for ...]
```

### 4.2【现状】连通性检查仅做 GET 根路径

`check_scrapyd_connectivity`（`check_app_config.py:398-429`）用线程池对每个节点 `session.get('http://ip:port', auth, timeout=10)`，断言 `status_code==200`，最后 `assert any(results)`（只要有一个节点能连通即放行）。

> 注意：连通性检查 GET 的是 scrapyd **根路径**而非 `daemonstatus.json`。task 描述中提到的「GET daemonstatus.json」更接近运行期 `ApiView` 的 daemonstatus 调用（§5.4），二者不要混淆。

### 4.3 配置流向图

```
settings 中的 SCRAPYD_SERVERS
  = ['usr:psw@ip:port#group', (usr,psw,ip,port,group), ...]
        │
        ▼  check_scrapyd_servers() 正则/解包 + 去重 + 按[group,ip,port]排序
   servers = [(group, ip, port, auth, public_url), ...]
        │
        ├─▶ config['SCRAPYD_SERVERS']             (host:port 字符串列表)
        ├─▶ config['SCRAPYD_SERVERS_GROUPS']
        ├─▶ config['SCRAPYD_SERVERS_AUTHS']
        └─▶ config['SCRAPYD_SERVERS_PUBLIC_URLS']
                  │  (4 个等长 list，下标 = node-1)
                  ▼
        BaseView.__init__ 按 self.node-1 取值
```

---

## 5. 单节点 scrapyd 调用封装

### 5.1【现状】`API_MAP`：语义 opt → scrapyd 真实端点

`scrapydweb/views/api.py:8`：

```python
API_MAP = dict(start='schedule', stop='cancel', forcestop='cancel', liststats='logs/stats')
```

其余 opt（`daemonstatus` / `listprojects` / `listversions` / `listspiders` / `listjobs` / `delversion` / `delproject`）直接同名映射。URL 拼接（`api.py:20`）：

```python
self.url = 'http://{}/{}.json'.format(self.SCRAPYD_SERVER, API_MAP.get(self.opt, self.opt))
```

| 语义 opt | scrapyd 端点 | 方法 | 关键 data/query |
| --- | --- | --- | --- |
| `start` | `schedule.json` | POST | `project, spider, jobid` |
| `stop` | `cancel.json` | POST | `project, job` |
| `forcestop` | `cancel.json` ×2 | POST | `project, job`（连发两次，§5.4） |
| `liststats` | `logs/stats.json` | GET | （logparser 提供） |
| `daemonstatus` | `daemonstatus.json` | GET | — |
| `listprojects` | `listprojects.json` | GET | — |
| `listversions` | `listversions.json` | GET | `?project=` |
| `listspiders` | `listspiders.json` | GET | `?project=[&_version=]` |
| `listjobs` | `listjobs.json` | GET | `?project=` |
| `delversion` | `delversion.json` | POST | `project, version` |
| `delproject` | `delproject.json` | POST | `project` |

URL/data 的构造分别在 `ApiView.update_url`（`api.py:32-40`）和 `update_data`（`api.py:42-54`）。`update_data` 里 `data` 为 `None` 即走 GET，否则走 POST——这与 `make_request` 的判定一致（见 §5.3）。

### 5.2【现状】`make_request`：唯一的 HTTP 调用集中点

`scrapydweb/views/baseview.py:285-354`。签名：

```python
def make_request(self, url, data=None, auth=None, as_json=True,
                 dumps_json=True, check_status=True, timeout=60):
```

要点：

| 维度 | 行为 | 代码位置 |
| --- | --- | --- |
| 方法选择 | `data` 为 None → `session.get`，否则 `session.post` | `baseview.py:305-308` |
| 连接复用 | 用 `common.py` 的**全局 `session`**（连接池 1000/1000） | `baseview.py:306-308`、`common.py:18-20` |
| 编码 | `r.encoding = 'utf-8'` | `baseview.py:309` |
| 异常归一化 | 网络/超时异常 → 返回 `(-1, {status:'error', message:str(err), ...})` | `baseview.py:310-318` |
| JSON 解析 | `r.json()`；`ValueError` 时把 `r.text` 当 message | `baseview.py:322-327` |
| message 规整 | 把 `\\n` 替换成真正换行 | `baseview.py:331-333` |
| 统一注入 | 往返回 dict 注入 `url/auth/status_code/when`，并 `setdefault('status', 'N/A')` | `baseview.py:334-335` |
| 返回值 | `(status_code, dict)`（`as_json=True`）或 `(status_code, text)` | `baseview.py:346, 354` |

> 这就是 scrapydweb 在认证、超时、错误处理上的**集中点**（行为参考）。dopilot 在 `apps/` 下全新复刻这一行为语义时，若希望上层逻辑（聚合/重试/告警/落库）保持一致，最简单的方式是沿用 `(status_code, dict)` 这个返回契约（见 §9.1）。

### 5.3【现状】调用契约的边界

- 返回的 `dict` 不保证是合法 scrapyd JSON：scrapyd 重启时可能返回 502 HTML，`r.json()` 抛 `ValueError` 后会被 `finally` 捕获，把 `r.text` 塞进 `message`（`baseview.py:325-327`）。
- 因此**调用方应检查 `status_code != 200` 或 `status != 'ok'`，而非假设永远是合法 JSON**。

### 5.4【现状】`ApiView.get_result`：按 opt 微调请求策略

`scrapydweb/views/api.py:56-65`：

```python
def get_result(self):
    timeout = 3 if self.opt == 'daemonstatus' else 60          # daemonstatus 超时 3s
    dumps_json = self.opt not in ['daemonstatus', 'liststats'] # 这两个不打印完整 json，减日志量
    times = 2 if self.opt == 'forcestop' else 1                # forcestop 连发两次 cancel
    for __ in range(times):
        self.status_code, self.js = self.make_request(self.url, data=self.data, auth=self.AUTH,
                                                      as_json=True, dumps_json=dumps_json, timeout=timeout)
        if times != 1:
            self.js['times'] = times
            time.sleep(2)                                       # 两次 cancel 之间 sleep 2s
```

### 5.5【现状】`ApiView.handle_result`：给失败/边界附加 tip

`scrapydweb/views/api.py:67-99` 把各种失败情况翻译成给用户的英文提示（tip），例如：

- `status_code != 200` 且 `opt == 'liststats'` → 提示安装/运行 logparser（`api.py:69-75`）；
- 其它非 200 → `"Make sure that your Scrapyd server is accessable."`（`api.py:77`）；
- `status != 'ok'` 且 message 含 `No such file|no active project` → 提示项目可能已删（`api.py:78-80`）；
- `liststats` 且 logparser 版本不匹配 → 提示升级 logparser（`api.py:89-97`）。

> 【改造 · i18n】`handle_result` 是英文文案最集中的地方之一，连同 `log.py`/`schedule.py` 的 `flash()` 文案，是 i18n 改造的优先目标（见 §9.6）。

### 5.6 单节点调用时序

```
浏览器 ── POST /3/api/stop/proj/jobid ──▶ ApiView
                                          │ __init__: API_MAP['stop']='cancel'
                                          │   url = http://<node3>/cancel.json
                                          │ update_data(): data={project, job}
                                          │ get_result(): make_request(POST)
                                          │   └─ session.post(url, data, auth=node3_auth, timeout=60)
                                          │ handle_result(): 失败时附加 tip
                                          ◀─ application/json {status, prevstate, node_name, tip?}
```

---

## 6. 多节点 fan-out 与响应聚合

### 6.1【现状·核心事实】服务端不并发聚合

对**读/写操作**（servers / jobs / multinode / schedule），每个 HTTP 请求只打**一个 node**。「对所有节点执行并汇总」靠浏览器逐节点发 XHR 实现。

`MultinodeView` 本身不发任何 scrapyd 请求，只渲染模板（`scrapydweb/views/overview/multinode.py:19-49`）：

```python
def dispatch_request(self, **kwargs):
    selected_nodes = self.get_selected_nodes()
    url_xhr = url_for('api', node=selected_nodes[0], opt=self.opt,
                      project=self.project, version_spider_job=self.version_job)
    ...
    kwargs = dict(..., selected_nodes=selected_nodes, url_xhr=url_xhr, ...)
    return render_template(self.template, **kwargs)   # 把列表 + 单节点 URL 模板交给前端
```

被勾选节点由 `get_selected_nodes` 从 POST 表单读出（`scrapydweb/views/baseview.py:257-262`，复选框 name 就是节点编号字符串）：

```python
def get_selected_nodes(self):
    selected_nodes = []
    for n in range(1, self.SCRAPYD_SERVERS_AMOUNT + 1):
        if request.form.get(str(n)) == 'on':
            selected_nodes.append(n)
    return selected_nodes
```

### 6.2【现状】前端 fan-out：`fireXHR` / `execXHR`

`scrapydweb/templates/scrapydweb/multinode_results.html`：

- 选中 >1 个节点时延时触发 `fireXHR()`，否则直接 `execXHR(node, url)`（`multinode_results.html:92-96`）；
- `fireXHR()` 遍历 `selected_nodes`，用正则把 URL 里的节点号替换成各节点编号（`multinode_results.html:100-110`）：

```javascript
function fireXHR(){
  for (var idx in selected_nodes) {
    var url = url_xhr.replace(/\/\d+/, '/'+selected_nodes[idx]);  // /3/api/.. → /N/api/..
    execXHR(selected_nodes[idx], url);
  }
}
```

- `execXHR()` 对每个节点独立发 XHR POST，`onreadystatechange` 回调把每节点的 `status`/`node_name`/`prevstate` 渲染进对应表格行（`multinode_results.html:113-144`）。**这就是「响应聚合」的实际位置——在浏览器 DOM 上**。

### 6.3 前端 fan-out 流程图

```
multinode_results.html (一次性服务端渲染，得到 selected_nodes + url_xhr)
        │
        ▼  window.onload
   selected_nodes.length > 1 ? fireXHR() : execXHR(one)
        │
        ▼  fireXHR(): 对每个 node
   url = url_xhr.replace(/\/\d+/, '/'+node)
   execXHR(node, url) ──XHR POST──▶ /N/api/<opt>/...  ──▶ ApiView ──▶ make_request ──▶ scrapyd N
        │                                                                                  │
        ◀── JSON {status, node_name, ...} ────────────────────────────────────────────────┘
        ▼
   DOM: #status_N / #node_name_N / #project_N ...  (逐行写入 = 聚合)
```

> Servers / Jobs / NodeReports / ClusterReports 等页面同理：服务端为每个节点生成一组 URL，前端用 Vue/JS 逐节点请求并展示。

### 6.4【陷阱】别误以为 scrapydweb 有现成的服务端 fan-out 池

参考 scrapydweb 行为时不要假设它存在「服务端多节点并发请求池」。scrapydweb 唯一在服务端做多节点串行下发的是 `TaskExecutor`（§7.2）。如果 dopilot 需要服务端聚合（例如同步 API、命令行触发），需要在 `apps/` 下**全新实现**这层，而非套用 scrapydweb 结构。

---

## 7. 调度下发的两条路径

### 7.1【现状】立即运行：先打首节点，其余前端补

`ScheduleRunView.handle_form`（`scrapydweb/views/operations/schedule.py:362-381`）：多节点时**只向首个被选节点同步发一次** `schedule.json`，并把 AUTH 切到该节点：

```python
if self.selected_nodes_amount:
    self.selected_nodes = self.get_selected_nodes()
    self.first_selected_node = self.selected_nodes[0]
    self.url = 'http://%s/schedule.json' % self.SCRAPYD_SERVERS[self.first_selected_node - 1]
    # Note that self.first_selected_node != self.node
    self.AUTH = self.SCRAPYD_SERVERS_AUTHS[self.first_selected_node - 1]   # 切到首节点的 auth
```

实际下发在 `handle_action`（`schedule.py:394-395`）。若首节点失败，整体中止并提示（`schedule.py:581-583`）；成功则其余节点交给前端 `schedule.xhr` 逐个补发（`ScheduleXhrView`，`schedule.py:595-614`，每次仍是单节点 `make_request`）。

```
            ┌─ first_selected_node ─▶ 服务端同步 make_request(schedule.json)  ── 失败则整体中止
selected ──┤
  nodes     └─ 其余 nodes ──▶ 前端 schedule.xhr 逐个 XHR ──▶ ScheduleXhrView ──▶ make_request
```

### 7.2【现状】定时任务（后台 push）：服务端串行 fan-out

`TaskExecutor.main` 串行遍历 `selected_nodes`（`scrapydweb/views/operations/execute_task.py:42-61`），对每个节点用 `get_response_from_view` **进程内自调用** `/N/schedule/task/`（`execute_task.py:75-104`），失败节点入 `nodes_to_retry` 延迟重试一次：

```python
for index, nodes in enumerate([self.selected_nodes, self.nodes_to_retry]):
    ...
    for node in nodes:
        result = self.schedule_task(node)   # 进程内 HTTP 自调用单节点端点
        ...
```

```python
def schedule_task(self, node):
    url_schedule_task = re.sub(REPLACE_URL_NODE_PATTERN, r'/%s/' % node, self.url_schedule_task)  # 正则换节点段
    js = get_response_from_view(url_schedule_task, auth=self.auth, data=self.data, as_json=True)
    assert js['status_code'] == 200 and js['status'] == 'ok', "Request got %s" % js
```

注意它用**正则替换 URL 节点段**而非 `url_for`（`execute_task.py:15, 82`），因为在 APScheduler 线程里 `url_for` 缺 `SERVER_NAME` 会失败（`execute_task.py:76-77` 注释）。结果写入 `TaskResult` / `TaskJobResult` 表（`execute_task.py:106-147`）。

> 这是服务端真正的「指定节点全部执行（push 模式）」。完整时序与 DB 交互见 `03-scheduler-engine.md`。

### 7.3【现状】`get_response_from_view`：进程内 HTTP 自调用

`scrapydweb/common.py:48-80`：用 `app.test_client()` 在同一进程内调用另一个视图，供 poll/定时任务/告警复用。带 auth 时注入 `Authorization: basic_auth_header(*auth)`（`common.py:52-54`），有 data 走 multipart POST（`common.py:57-58`），可选 `as_json` 把响应 text 解析成 dict（`common.py:64-78`，并兜底从 500 页面正则提取错误信息）。

---

## 8. logparser 日志解析与统计流程

### 8.1【现状】logparser 是各 scrapyd 主机上的独立 daemon

logparser 把 scrapyd 主机上的 `*.log` 解析成同名 `*.json`，scrapydweb 通过 HTTP 拉取或读取本地文件。它可由 scrapydweb 自动拉起（`init_logparser` → `start_logparser`，`scrapydweb/utils/sub_process.py:53-82`，仅当 `ENABLE_LOGPARSER=True` 且配置了 `LOCAL_SCRAPYD_LOGS_DIR`），也可在每台 scrapyd 主机上独立运行 `logparser` 命令。

### 8.2【现状】`LogView` 的统计获取优先级（四级回退）

`scrapydweb/views/files/log.py:116-165`，按以下顺序尝试：

| 顺序 | 来源 | 方法 | 代码 |
| --- | --- | --- | --- |
| 1 | 本地 `.json`（仅本机节点） | 读 `self.json_path` | `read_local_stats_by_logparser`，`log.py:172-191` |
| 2 | 远程 `.json` | `make_request(self.json_url)` | `request_stats_by_logparser`，`log.py:193-219` |
| 3 | 备份 stats | 读 `STATS_PATH` 下备份 | `load_backup_stats`，`log.py:317-336` |
| 4 | 兜底现场解析 | `from logparser import parse`，对整段日志 `parse(self.text)` | `log.py:14, 149-153` |

整段日志本身也走「本地文件优先、否则 HTTP 拉取」：`read_local_scrapy_log`（`log.py:221-234`）→ `request_scrapy_log`（`log.py:236-248`，仍是 `make_request`）。

### 8.3【现状】版本严格校验

logparser 解析结果里的 `logparser_version` 必须与 scrapydweb 内置版本**严格相等**，否则 `flash` 报错且不出统计：

- 本地 stats：`log.py:181-185`；
- 远程 stats：`log.py:206-211`；
- 备份 stats：`log.py:325-329`；
- `ApiView.liststats`：`api.py:90-97`。

内置版本来自 `from logparser import __version__`（`baseview.py:9, 26`）。

### 8.4【现状】后台 Poll 子进程主动拉取 + 触发告警

`scrapydweb/utils/poll.py`（独立子进程，由 `init_poll` 拉起，仅当 `ENABLE_MONITOR=True`，`sub_process.py:85-123`）：

1. 对每个 scrapyd `GET http://host:port/jobs`（`poll.py:188`），用 `JOB_PATTERN` 正则解析 `/jobs` **HTML 页面**得到 running/finished 任务（`poll.py:28-42, 101-121`）；
2. 用集合 diff 识别新完成任务（`update_finished_jobs`，`poll.py:205-227`）；
3. 对每个任务**反向 POST** scrapydweb 自身的 `/<node>/log/stats/.../?job_finished=...`（`poll.py:81, 123-146`）触发统计抓取与监控告警。

`LogView.dispatch_request` 中 `if self.ENABLE_MONITOR and self.POST: self.monitor_alert()`（`log.py:168-169`）——**只有 poll.py 的 POST 才会触发告警**。`monitor_alert`（`log.py:404-417`）依据阈值决定是否 Slack/Telegram/Email 告警，甚至回头调用 `/api/stop|forcestop` 自动停爬（`log.py:478-487`）。

```
Poll 子进程 (每 POLL_ROUND_INTERVAL，默认 300s)
   │ for each scrapyd:
   │   GET http://host:port/jobs  ──正则 JOB_PATTERN──▶ running/finished jobs
   │   for each job:
   │     POST scrapydweb /N/log/stats/proj/spider/job/?job_finished=…
   │            │
   │            ▼  LogView (POST + ENABLE_MONITOR)
   │        优先 logparser 取 stats ─▶ monitor_alert()
   │            └─▶ 阈值命中 → Slack/Telegram/Email + (可选) 自动 stop/forcestop
```

### 8.5【陷阱】logparser 与 Poll 的脆弱点

- **「实时日志」并非真正流式**：`LogView` 的刷新是 JS 轮询 `location.reload(true)`（`log.py:355, 376`）+ 后台 Poll 周期拉取，延迟大。
- **Poll 靠正则解析 HTML**：`JOB_PATTERN`（`poll.py:28-41`）解析 scrapyd `/jobs` 的 HTML，scrapyd 改版页面会直接打挂解析。
- **版本耦合**：logparser 版本必须与内置版本完全一致，运维上要同步升级。
- **格式耦合**：logparser 只认 scrapy 日志格式。Docker/script 类任务**没有 scrapy 日志结构，无法直接复用 logparser**（见 §9.4）。

---

## 9. 与 dopilot 新执行器的关系（改造建议）

> 本节均为 **【改造】 / 【开放问题】**，是设计意见而非现有实现。dopilot 要把「节点」从 scrapyd-only 扩展为三类被调度对象：① scrapy 爬虫（经 scrapyd，现状）；② Docker 常驻爬虫；③ Python3 一次性脚本。

### 9.1 引入「执行后端（Executor）」抽象层

**问题**：当前所有「下发动作」都硬编码成对 scrapyd 的 `*.json` HTTP 调用（`ApiView` 的 `API_MAP` + `make_request`）。

**建议**：在节点配置里增加 `type`（`scrapyd` / `docker` / `script`），在 `ApiView` / `ScheduleRunView` 入口按 `type` 分派：

```
            ┌─ type=scrapyd ─▶ ScrapydExecutor  → 现有 make_request → scrapyd *.json
dispatch ──┤─ type=docker  ─▶ DockerExecutor   → docker SDK / worker agent (start/stop/exec)
            └─ type=script  ─▶ ScriptExecutor   → worker agent 跑 python3
```

| 触点 | 文件 | 现状 | 改造方向 |
| --- | --- | --- | --- |
| API 端点映射 | 行为参考：`scrapydweb/views/api.py`（`API_MAP`、`ApiView`） | scrapydweb 硬编码 scrapyd 端点 | dopilot 全新实现：按 node.type 分派到不同 Executor |
| HTTP 封装 | 行为参考：`scrapydweb/views/baseview.py`（`make_request`） | scrapydweb 只发 scrapyd HTTP | dopilot 全新实现 `ScrapydExecutor`/`DockerExecutor`/`ScriptExecutor`，**沿用 `(status_code, dict)` 返回契约** |

**契约要求**：dopilot 全新实现的各 Executor，其返回值建议与 scrapydweb `make_request` 的行为语义一致（`(status_code, dict)`，dict 至少含 `status`/`message`/`status_code`），这样上层的聚合（§6）、重试/落库（§7.2）、告警（§8.4）行为语义可一并对齐复刻。

### 9.2 节点选择策略：全部执行 vs 随机选一个

**现状**：只有「全部执行」——`TaskExecutor` 串行遍历 `selected_nodes`（`execute_task.py:42-61`）；`ScheduleRunView` 取首节点（`schedule.py:362-368`）。

**建议**：新增策略字段（如 `task.dispatch_strategy = all | random`）：

- `all`：保持现状遍历；
- `random`：在 `execute_task` / `ScheduleRunView` 决定 `selected_nodes` 时用 `random.choice` 选一个（可结合 `daemonstatus`/可用性过滤后再选）。

| 触点 | 文件:位置 | 说明 |
| --- | --- | --- |
| 定时任务遍历 | `execute_task.py:42-61`（`TaskExecutor.main`） | random 时只取一个 node |
| 立即运行取节点 | `schedule.py:362-368`（`handle_form`） | random 时覆盖 `selected_nodes` |
| 存储字段 | `models.py:103`（`Task.selected_nodes = db.Column(db.Text())`） | 目前以 JSON 字符串存整数列表，需新增列或扩展该 JSON 结构承载策略 |

### 9.3 推模式主动下发到指定节点

**现状**：push 实现是 APScheduler 线程里 `get_response_from_view` 进程内自调用 `/N/schedule/task/`（`execute_task.py:88`）。

**建议**：dopilot 全新复刻这一入口模式的行为语义，但对 docker/script 节点把「进程内自调用 scrapyd 视图」改为「调用 worker agent 的下发 API」。外部触发（如 RemoteTrigger/PushNotification 一类机制）可统一挂到同一个 Executor 入口，沿用其重试/落库行为语义。

| 触点（行为参考） | 文件 | 说明 |
| --- | --- | --- |
| 下发执行器 | `execute_task.py`（`TaskExecutor`） | dopilot 全新实现统一入口；按 node.type 选择下发协议 |
| 进程内自调用 | `common.py:48-80`（`get_response_from_view`） | scrapyd 走同语义自调用；docker/script 改为 agent API 调用 |

### 9.4 实时日志流

**现状**：`utf8_realtime` / `url_refresh` 走 JS `location.reload`（`log.py:349-355, 370-376`）+ 后台 Poll 周期拉取，**非流式**。

**建议**：为 docker/常驻进程接入真正的流式通道——新增 SSE 流式端点（dopilot v1 见决策#11；v1 不引入 WebSocket）或 `docker logs --follow`，新增一个流式 `LogView`/端点替代 reload 轮询；scrapy 部分仍可走现有 logparser 拉取。

| 触点 | 文件 | 说明 |
| --- | --- | --- |
| 日志视图 | `scrapydweb/views/files/log.py`（`utf8_realtime`/`url_refresh`） | 新增流式端点 |
| 后台拉取 | 行为参考：`scrapydweb/utils/poll.py` | docker/script 任务无 scrapy 日志格式，dopilot 需另设解析/统计路径（logparser 行为不适用于此，§8.5） |

### 9.5 节点配置结构扩展（类型/能力/凭证）

**现状**：节点元数据被拆成 4 个等长 list，用 `node-1` 索引访问（`check_app_config.py:392-395`、`baseview.py:193-197`），且 node 编号随排序漂移（§3.3）。

**建议**：dopilot 不沿用 scrapydweb 的「4 个并行 list + `node-1` 下标」结构，而在 `apps/` 下全新设计为 `list[dict]`（每节点一个对象）或 DB 表，每节点对象携带 `type` / `labels` / `docker-endpoint` / `agent-url` / 凭证等字段。否则字段越加越难维护，且寻址脆弱性会随节点种类增多而放大。

| 触点（行为参考） | 文件:位置 | 说明 |
| --- | --- | --- |
| 配置解析 | `check_app_config.py:360-395`（`check_scrapyd_servers`） | dopilot 全新实现：输出结构从 4 list → list[dict] / DB |
| 取值 | `baseview.py:189-197`（`__init__`） | dopilot 全新实现：从对象/表取值，建议用稳定主键替代整数下标 |

### 9.6 i18n（中文）

**现状**：模板与视图中大量英文字符串硬编码，文案集中在：

- `ApiView.handle_result`（`api.py:67-99`）的 tip；
- `LogView` 的各处 `flash()`（`log.py` 多处，如 `log.py:90, 200-204, 247`）；
- `schedule.py` 的 `flash`/alert/postfix 文案（如 `schedule.py:470-475, 582-585`）。

**行为参考**：`handle_result` 与 `LogView` 的 tip/flash 是 scrapydweb 文案最密集处。dopilot 的 i18n 走**前端 vue-i18n**(`apps/web`,见 `../dopilot/04-gap-i18n.md`)——后端 `/api/v1` 只回结构化数据/错误码,**不引入 Flask-Babel/后端 gettext**;此处仅作 scrapydweb 文案分布的行为参考。

---

## 10. 陷阱速查表

| # | 陷阱 | 出处 |
| --- | --- | --- |
| 1 | **服务端无多节点并发聚合**；读/写操作每请求只打一个 node，聚合在浏览器 JS（fireXHR/execXHR/Vue）。唯一服务端串行下发是 `TaskExecutor` | §6.1 / `multinode.py`、`multinode_results.html`、`execute_task.py` |
| 2 | **node 编号会漂移**：4 个并行 list 经 `sorted(set(...))` 重排（按 group/ip/port），增删节点导致 node 编号变化，历史 `Task.selected_nodes` 可能指向错节点 | §3.3 / `check_app_config.py:382-388` |
| 3 | **AUTH 序列化为 list 后必须 `tuple()`**，否则 requests 报 `'list' object is not callable` | `poll.py:189-190` |
| 4 | **`make_request` 返回的 dict 不保证是合法 JSON**：scrapyd 重启返回 502 HTML 时 `r.json()` 抛 `ValueError`，`r.text` 被塞进 message；调用方应检查 `status_code!=200` / `status!='ok'` | §5.3 / `baseview.py:322-327` |
| 5 | **`forcestop` 连发两次 cancel**（中间 sleep 2s），照搬到 docker/script 会造成双重停止语义问题 | §5.4 / `api.py:59-65` |
| 6 | **「实时日志」非流式**：JS `location.reload(true)` + 后台 Poll（默认 300s）；Poll 靠正则解析 scrapyd `/jobs` HTML，scrapyd 改版即打挂 | §8.5 / `log.py`、`poll.py:28-41` |
| 7 | **logparser 是各 scrapyd 主机的外部 daemon**，且版本严格相等才出统计；docker/script 无 scrapy 日志格式，无法复用 | §8.3 / §8.5 / `log.py:181-185` 等 |
| 8 | **`execute_task` 跑在 APScheduler 线程**，大量用 `with db.app.app_context()` + `get_response_from_view`；依赖 metadata 表的 url，`url_for` 在线程里会失败（故改用正则替换 URL 节点段） | §7.2 / `execute_task.py:76-82` |
| 9 | **脏目录**：`data/demo_projects` 下有中文重复目录 `'ScrapydWeb_demo - 副本'`，`BaseView.safe_walk` 专门处理非法/非 unicode 文件名 | `baseview.py:391-429` |

---

## 11. 与其它文档的衔接

| 主题 | 参见 |
| --- | --- |
| 配置解析全流程、4 个并行列表来源 | `01-bootstrap-and-config.md` |
| `Task` / `TaskResult` / `TaskJobResult` 模型字段 | `02-data-model.md` |
| 定时引擎、`TaskExecutor` 完整时序与 DB 交互 | `03-scheduler-engine.md` |
| 本文聚焦：单节点 API 封装、fan-out 与聚合、logparser 流程、与新执行器关系 | 本文 |
