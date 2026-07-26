---
task: ci-docker-login-before-buildx
date: 2026-07-26
rounds: 1
verdict: pass
---

# 任务小结:docker workflow 登录前置,使 binfmt 与 buildkit 镜像走认证拉取

## 起因

`docker` workflow 在 `Set up Docker Buildx` 步骤失败:拉取 buildkit **自身
容器镜像** `moby/buildkit:buildx-stable-1` 时
`Get "https://registry-1.docker.io/v2/": context deadline exceeded`。

该失败早于任何 Dockerfile / build-arg / base 镜像被使用,且最近一次提交
(`74c1ab1`)只动了 `docs/`、`.ai/` 与 `.ai-workflow/TEMPLATE-VERSION`,零个
构建输入;用户同时反馈**其他仓库的自动构建也在出问题**——指向 Docker Hub
侧的可用性/限流,而非本仓库配置错误。

但配置里确有一处放大了暴露面:`Login to Docker Hub` 原先排在
`Set up QEMU` 与 `Set up Docker Buildx` **之后**,而这两个 action 都通过
runner 上的 docker daemon 拉镜像(`tonistiigi/binfmt`、`moby/buildkit`),
因此那两次拉取全程**匿名**,吃 Docker Hub 匿名额度(按 runner 出口 IP 计,
与同 IP 上其它 GitHub 用户共享)。

## 改动

| 文件 | 摘要 |
|---|---|
| `.github/workflows/docker.yml` | `base` 与 `app` 两个 job 各把 `Login to Docker Hub` 块整体上移到 `Set up QEMU` 之前。改后顺序均为 `checkout → Login → QEMU → Buildx → …`。两处 5 行块**逐字节不变**,纯位置变更 |
| `.ai/2026-07-26/ci-docker-login-before-buildx/evidence/` | 4 个核验脚本(`step-order-check.py`、`pure-reorder-check.sh`、`reverse-selfcheck.sh`、`env-scope-check.sh`、`changeset-check.sh`)+ 5 条用例原始输出 |

正确性依据:`docker/login-action` 只执行 `docker login` 并写
`~/.docker/config.json`,不依赖 buildx;块内引用的 `DOCKERHUB_USERNAME`
定义在 **workflow 级 `env:`**,对 job 内任意位置的步骤可见;块内无
`steps.*` 依赖。三点均由 TC-05 断言。

**明确未做**:不删 QEMU 步骤(单架构下确实多余,但该 workflow 支持用
`vars.DOCKER_PLATFORMS` 切多架构,删除会在切换时静默破坏多架构构建,须
单独评估);不改 action 版本;不加 registry mirror / driver-opts;不动
`deploy/docker/` 与其余构建逻辑。

## 验证边界(不回避)

本地无法触发 GitHub Actions,**5 条用例均未、也不声称验证 CI 侧运行结果**。
它们验证的是改动本身正确且无副作用。登录前置能否减少
`registry-1.docker.io` 超时,只能由推送后的 workflow 实跑观察;且该改动
**不保证**消除此类失败——Docker Hub 整体降级时认证拉取同样会超时。它消除
的是"匿名共享额度被打满"这一个可控变量。

## 评审历程

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| impl-01 | **pass** | 无 blocker / 无 major;1 minor(见下) |

本任务触及源文件 1 个(≤10),按 CLAUDE.md 未触发 plan 阶段 Codex 评审闸;
用户未要求放宽轮次,两个上限字段均未写入 frontmatter,按默认 3 轮。

## 测试

5 条用例全 A 档、C 档 0 条,全部 pass(exit=0)。含 1 处反向自检(旧顺序
副本必须被判失败,且必须是**顺序违例**而非崩溃)与 1 处集合相等断言
(改动集恰好 1 个源文件)。

自测中自行发现并修掉两个问题:① `step-order-check.py` 因 PyYAML 按 YAML 1.1
把裸 `on:` 解析成布尔 `True` 而在 `sorted(wf.keys())` 崩溃;② 更要紧的是
**TC-03 曾因此假通过**——反向自检原本只断言"非零退出",而副本是因崩溃退出、
不是因顺序违例退出,自检却报 PASS。已加固为同时断言输出含顺序违例文案并
统计条数(期望 4 条 = 2 job × 2 个后置步骤)。

## 遗留 minor 及处置

| 编号 | 内容 | 用户决定 |
|---|---|---|
| impl-01 R-01 | `evidence/reverse-selfcheck.sh:53` 的**辅助打印**命令有语法错误:`python3 -c '…'` 单引号串中的 `\"` 原样传入 Python,f-string 表达式内不允许反斜杠,导致 `SyntaxError`(见 `tc03-reverse-selfcheck.txt:9`)。该命令仅用于打印"副本步骤顺序一览",失败后脚本继续执行,**核心反向断言仍检出 4 条违例、正向断言仍 PASS**,不影响验收结论;但证据中留有误导性 traceback,且该辅助清单实际没打出来。修法:先把标签赋给局部变量再放进 f-string,并重新生成 TC-03 证据 | **本次不修**(用户 2026-07-26 选择评审通过后直接提交,未另行指定处置;该瑕疵仅影响辅助输出,不影响任一断言的有效性,留待后续按需处理) |
