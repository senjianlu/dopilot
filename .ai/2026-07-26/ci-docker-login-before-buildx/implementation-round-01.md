---
task: ci-docker-login-before-buildx
round: 01
date: 2026-07-26
---

# 实现记录:第 01 轮

## 本轮改动

按 plan 实现。源文件改动 1 个,为**纯步骤换序**。

| 文件 | 改动摘要 |
|---|---|
| `.github/workflows/docker.yml` | `base` job(原 42-52 行)与 `app` job(原 159-169 行)各把 `Login to Docker Hub` 步骤块整体上移到 `Set up QEMU` 之前。改后两个 job 的步骤顺序均为 `checkout → Login → QEMU → Buildx → …`。两处 5 行块逐字节不变,只改位置 |
| `.ai/2026-07-26/ci-docker-login-before-buildx/evidence/step-order-check.py` | 新增。TC-01:PyYAML 解析 workflow,断言两个 job 中 `idx(Login) < idx(QEMU)` 且 `< idx(Buildx)` |
| `…/evidence/pure-reorder-check.sh` | 新增。TC-02:与 `HEAD` 版本比对——逐行排序后完全相同、步骤名多重集不变、Login 块逐字节一致 |
| `…/evidence/reverse-selfcheck.sh` | 新增。TC-03:脚本自己生成旧顺序副本并断言其被判失败 |
| `…/evidence/env-scope-check.sh` | 新增。TC-05:断言 `DOCKERHUB_USERNAME` 在 workflow 级 env、login 块不依赖 `steps.*`、checkout < login |
| `…/evidence/changeset-check.sh` | 新增。TC-04:改动集与 plan 声明清单集合相等 |
| `…/evidence/tc0{1,2,3,4,5}-*.txt` | 5 条用例的完整原始输出(命令 + stdout/stderr + 退出码) |

### 自测中发现并修掉的两个问题

1. **`step-order-check.py` 崩溃**:PyYAML 按 YAML 1.1 把裸 `on:` 解析成布尔
   `True`,顶层 key 混有 `bool` 与 `str`,`sorted(wf.keys())` 抛
   `TypeError: '<' not supported between instances of 'bool' and 'str'`。
   改为 `sorted(map(str, wf.keys()))` 并加注释说明成因。
2. **TC-03 曾假通过**(更要紧):在上述崩溃存在时,反向自检只断言"旧顺序
   副本非零退出",而副本是**因崩溃**退出、不是因顺序违例退出,自检却报了
   PASS。已加固:除 `rc != 0` 外,追加断言输出中必须出现顺序违例判定文案
   (`未早于`),并统计违例条数(期望 4 条 = 2 job × 2 个后置步骤)。修复后
   实测旧顺序副本给出 4 条违例、当前版本 PASS。

## 修复对照

不适用(第 1 轮,无上一轮评审问题)。

> 本任务触及源文件 1 个(≤10),按 CLAUDE.md 未触发 plan 阶段 Codex 评审闸;
> 用户未要求放宽轮次,`plan_review_max_rounds` / `impl_fix_max_rounds` 均未
> 写入 frontmatter,修复轮上限按默认 3。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-step-order.txt`(exit=0)。两个 job 步骤序列均为 `[0] checkout / [1] Login / [2] QEMU / [3] Buildx / …`;下标断言 `Login(1) < QEMU(2)`、`Login(1) < Buildx(3)` 各 2 条全 OK |
| TC-02 | A | pass | `evidence/tc02-pure-reorder.txt`(exit=0)。① 改前(HEAD)与改后两版**逐行排序后完全相同**;② `base` 9 步、`app` 6 步,步骤名多重集不变;③ Login 块 5 行逐字节一致;④ 附完整 `diff -u` 供人工过目 |
| TC-03 | A | pass | `evidence/tc03-reverse-selfcheck.txt`(exit=0)。旧顺序副本(Login 排在 Buildx 之后)被判 FAIL 并给出 **4 条**顺序违例(每 job 各 2 条),当前工作区版本判 PASS —— 顺序断言正反两向均有效 |
| TC-04 | A | pass | `evidence/tc04-changeset.txt`(exit=0)。源文件改动集**恰好** = `.github/workflows/docker.yml`;`apps/`、`packages/`、`deploy/`、`configs/`、`scripts/`、`examples/`、`tests/`、`docs/`、`.ai-workflow/`、`.claude/`、`.agents/`、`.githooks/` 全部零改动;`AGENTS.md`、`CLAUDE.md`、`README.md` 等 7 个根文件零改动 |
| TC-05 | A | pass | `evidence/tc05-env-scope.txt`(exit=0)。`DOCKERHUB_USERNAME` 确在 **workflow 级 env**(`['DOCKERHUB_USERNAME', 'DOCKER_PLATFORMS']`),对 job 内任意位置可见;login 块只引用 `env.*` 与 `secrets.*`、无 `steps.*` 依赖;两个 job 均 `checkout(0) < login(1)` |

无 `blocked` 项,无 `fail` 项;档位未做任何下调(5 条全 A 档,C 档 0 条)。

## 与方案的偏差

无。

**须明确声明的验证边界**(plan 已写明,此处复述以免误读):本地无法触发
GitHub Actions,以上 5 条用例**均未、也不声称**验证 CI 侧运行结果。它们
验证的是改动本身正确且无副作用(YAML 合法、顺序正确、纯换序无内容漂移、
表达式作用域仍成立、改动集边界)。**登录前置能否减少
`registry-1.docker.io` 超时,只能由用户推送后观察 workflow 实际运行**;
且该改动不保证消除此类失败——Docker Hub 整体降级时认证拉取同样会超时。
