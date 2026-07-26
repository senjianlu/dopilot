---
status: approved
task: ci-docker-login-before-buildx
date: 2026-07-26
approved_at: 2026-07-26 18:13:04+0900
---

# 方案:docker workflow 登录前置,使 binfmt 与 buildkit 镜像走认证拉取

## 背景与目标

### 故障现象

`docker` workflow 在 `Set up Docker Buildx` 步骤失败:

```
#1 [internal] booting buildkit
#1 pulling image moby/buildkit:buildx-stable-1
#1 ERROR: Error response from daemon:
   Get "https://registry-1.docker.io/v2/": context deadline exceeded
```

失败发生在 buildkit **自身容器**启动阶段,早于任何 Dockerfile、build-arg、
base 镜像被使用;最近一次提交(`74c1ab1`)只动了 `docs/`、`.ai/` 与
`.ai-workflow/TEMPLATE-VERSION`,零个构建输入,不可能是诱因。用户反馈
**其他仓库的自动构建也同时出问题**,指向 Docker Hub 侧的可用性/限流,而非
本仓库配置错误。

### 配置里被放大的暴露面

`.github/workflows/docker.yml` 的 `base` 与 `app` 两个 job 目前都是同一顺序
(`docker.yml:42-52` 与 `docker.yml:159-169`):

```
1. Set up QEMU          (docker/setup-qemu-action)   → 拉 tonistiigi/binfmt
2. Set up Docker Buildx (docker/setup-buildx-action) → 拉 moby/buildkit ← 失败点
3. Login to Docker Hub  (docker/login-action)
```

两个 action 都是**通过 runner 上的 docker daemon 拉镜像**,而登录发生在它们
**之后**——因此这两次拉取全程是**匿名**的,吃 Docker Hub 匿名拉取额度
(按 runner 出口 IP 计,与同一 IP 上其它 GitHub 用户共享)。

`docker/login-action` 的作用是执行 `docker login` 并把凭据写入
`~/.docker/config.json`,它**不依赖 buildx**,可以独立于且早于这两步执行;
之后 daemon 拉 `tonistiigi/binfmt` 与 `moby/buildkit` 就会带上凭据,走认证
额度。

### 目标

把 `Login to Docker Hub` 移到 `Set up QEMU` 之前(两个 job 各一处),使
workflow 中**所有**经 docker daemon 的镜像拉取都在登录之后发生。**纯步骤
换序,不改任何步骤的内容、参数或构建逻辑。**

### 诚实的预期边界

本改动**不能保证**消除该类失败:若 Docker Hub 本身不可达或整体降级,认证
拉取同样会超时。它降低的是"匿名共享额度被打满"这一类可控风险,并让失败
原因更可归因。真实效果只能由后续 CI 运行观察,本任务的测试用例**不声称**
验证了 CI 侧结果(见「测试用例」的说明)。

## 改动范围

### 改动的文件(1 个)

| # | 文件 | 动作 |
|---|---|---|
| 1 | `.github/workflows/docker.yml` | `base` job:把 `Login to Docker Hub` 步骤块整体移到 `Set up QEMU` 之前;`app` job:同样处理。两处均为**整块移动**,块内文本逐字节不变 |

### 任务过程产物

`.ai/2026-07-26/ci-docker-login-before-buildx/` 下的 plan.md、
implementation-round-NN.md、review-round-NN-*.md、summary.md,以及
`evidence/` 下的核验脚本与原始输出。

### 明确不动

- **不动 QEMU 步骤本身**。`DOCKER_PLATFORMS` 默认 `linux/amd64` 单架构时
  `setup-qemu-action` 其实是多余的,去掉可再省一次 Docker Hub 拉取;但用户
  本次只要求"登录前置",且该 workflow 支持用仓库变量
  `vars.DOCKER_PLATFORMS` 切多架构,删 QEMU 会在切换时静默破坏多架构构建
  —— 需要单独评估,**列为后续可选任务,本次不做**。
- **不改任何 action 版本**(`@v4` / `@v6` 保持原样)。
- **不改构建逻辑**:`deps` job、tag 计算、manifest 探测、`build-push-action`
  的 context/file/target/platforms/cache 全部不动。
- **不改 `deploy/docker/` 下的 Dockerfile 与 compose**。
- **不加 registry 镜像源 / driver-opts**:改 buildkit 镜像来源(如指向其它
  registry 的 mirror)能绕开 Docker Hub,但引入新的外部依赖与信任面,超出
  本次范围;若登录前置后仍频繁失败,再单独立项评估。
- **不加 docs/decisions 记录**:本次是 CI 步骤换序,未改变架构或推翻既有
  决策,不满足 `docs/decisions/README.md` 的"一事一文"立项条件。

## 实现方案

对 `.github/workflows/docker.yml` 的两个 job 各做一次**整块移动**,目标顺序:

```
1. Login to Docker Hub   ← 上移到此处
2. Set up QEMU
3. Set up Docker Buildx
```

移动的块在 `base` job 为 `docker.yml:48-52`、在 `app` job 为
`docker.yml:165-169`,内容均为:

```yaml
      - name: Login to Docker Hub
        uses: docker/login-action@v4
        with:
          username: ${{ env.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
```

两个块**逐字节保持不变**,只改所在位置。

正确性依据:块内引用的 `env.DOCKERHUB_USERNAME` 定义在 **workflow 级 `env:`**
(`docker.yml:12-14`),对该 job 内任意位置的步骤都可见;`secrets.DOCKERHUB_TOKEN`
同理。因此上移不会造成表达式解析不到值。两个块也不依赖 `steps.*` 的任何
输出(`checkout` 之后即可执行)。

## 测试用例

**执行环境**:所有用例 cwd 一律为仓库根 `/home/rabbir/Projects/dopilot`,
表中路径均为仓库根相对路径;留证命令统一为
`<命令> > <证据文件> 2>&1; echo "exit=$?" >> <证据文件>`。

**关于 CI 侧验证的说明(不回避)**:本任务无法在本地触发 GitHub Actions,
因此**没有任何一条用例声称验证了 CI 运行结果**。下列用例验证的是改动本身的
正确性与无副作用(YAML 合法、顺序正确、纯换序无内容漂移、改动集边界);
真实效果须由用户推送后观察 workflow 运行,该观察结果不计入本任务的验收。

| 编号 | 档位 | 前置条件 | 步骤(cwd=仓库根) | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 改动已落地 | `python3 .ai/2026-07-26/ci-docker-login-before-buildx/evidence/step-order-check.py .github/workflows/docker.yml` —— 用 PyYAML 解析 workflow,对 `base` 与 `app` 两个 job 分别取步骤 `name` 序列,断言 `Login to Docker Hub` 的下标 **小于** `Set up QEMU` 且小于 `Set up Docker Buildx` | 退出码 0;打印两个 job 的完整步骤名序列与三者下标,均满足 login < qemu < buildx | 命令 + 完整输出 + 退出码 → `evidence/tc01-step-order.txt`;脚本 `evidence/step-order-check.py` |
| TC-02 | A | 改动已落地,尚未提交 | `bash .ai/2026-07-26/ci-docker-login-before-buildx/evidence/pure-reorder-check.sh` —— 从 `git show HEAD:.github/workflows/docker.yml` 取改前版本,与工作区版本对比:① 两版**逐行排序后完全相同**(证明只换序、无增删改任何一行);② 每个 job 的步骤**名称多重集**相同;③ `Login to Docker Hub` 块的 5 行内容在两版中逐字节一致 | 退出码 0,三项断言全 PASS | 命令 + 完整输出 + 退出码 → `evidence/tc02-pure-reorder.txt` |
| TC-03 | A | 改动已落地 | **异常/反向路径**:`bash .ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh` —— 由脚本自己在 scratchpad 生成一份**旧顺序**(login 在 buildx 之后)的 workflow 副本,对其运行 TC-01 的同一顺序断言脚本,断言其**必须非零退出**;再对当前工作区版本运行,断言退出 0 | 退出码 0;旧顺序副本被判 FAIL 并指出违例 job,现版本判 PASS(证明顺序断言不是恒真通过) | 命令 + 完整输出 + 退出码 → `evidence/tc03-reverse-selfcheck.txt`;脚本 `evidence/reverse-selfcheck.sh` |
| TC-04 | A | 改动已落地,尚未提交 | `bash .ai/2026-07-26/ci-docker-login-before-buildx/evidence/changeset-check.sh` —— 取 `git status --porcelain --untracked-files=all`,与本方案声明的清单做**集合相等**断言 | 退出码 0;改动集**恰好** = `.github/workflows/docker.yml` + 本任务 `.ai/` 目录产物;`apps/`、`packages/`、`deploy/`、`configs/`、`scripts/`、`examples/`、`tests/`、`docs/`、`.ai-workflow/`、`.claude/` 零改动 | 命令 + 完整输出 + 退出码 → `evidence/tc04-changeset.txt` |
| TC-05 | A | 改动已落地 | `bash .ai/2026-07-26/ci-docker-login-before-buildx/evidence/env-scope-check.sh` —— 断言 `env.DOCKERHUB_USERNAME` 定义在 **workflow 级 `env:`**(而非某个 job/step 级),证明 login 块上移后该表达式仍可解析;同时断言两个 job 中 login 块出现在 `actions/checkout` **之后**(login 不依赖 checkout,但保持在其后可避免无谓的顺序意外) | 退出码 0;打印 `env:` 所在层级与两个 job 中 checkout / login 的下标 | 命令 + 完整输出 + 退出码 → `evidence/tc05-env-scope.txt` |

档位说明:5 条全 A 档,C 档 0 条(无人工交互项)。非 happy-path 覆盖:
TC-03(旧顺序副本必须被判失败)、TC-04(集合相等,拦截意外改动)、
TC-02 的逐行排序比对(任何一行内容漂移都会被检出)。

## 风险与回滚

| 风险 | 说明 | 对策 |
|---|---|---|
| **换序时误改块内容** | 手工移动 YAML 块容易带进缩进或字符改动 | TC-02 的"两版逐行排序后完全相同"断言可检出任何一行的增删改;TC-01 另行验证 YAML 仍可解析 |
| **改动不解决问题** | Docker Hub 整体降级时认证拉取同样超时 | 已在「诚实的预期边界」写明,不夸大效果;若推送后仍失败,再评估 registry mirror / driver-opts 方案(本次明确排除) |
| **误伤多架构构建** | 若顺带删掉 QEMU,`vars.DOCKER_PLATFORMS` 切多架构时会静默失效 | 本次**不动 QEMU**,已列入「明确不动」 |
| **CI 效果无法本地验证** | 本地无法触发 Actions | 用例不声称验证 CI 结果;真实效果由用户推送后观察,不计入验收 |

**回滚**:单文件、纯步骤换序,无状态、无迁移。回滚 = `git revert` 该提交,
workflow 立即回到当前顺序。
