---
name: rawf-review
description: rawf 工作流第 4 步:通过 review.sh 调用 Codex 评审当前改动,并按结果分流(通过/修复轮/升级人工)。每轮 implementation-round 产物写完后立即使用。
---

# rawf-review:评审与分流

1. 运行 `bash .ai-workflow/scripts/review.sh`。评审只能经此脚本,不得以
   自查代替 Codex 评审。**必须以后台方式运行**并等待完成:评审耗时波动
   大,前台命令的超时上限(约 10 分钟)扛不住,超时被杀会遗留
   `.review-lock` 锁目录。退出码非 0/1(即 3)= 评审执行异常,把 stderr
   报给用户后停下,不要自行绕过;唯一例外是报"锁已存在"且确认无并发
   评审进程(如 `pgrep -fl 'codex exec'` 为空)时,删除锁目录后重跑一次。
2. 读取新生成的 review-round-<NN>-<pass|fail>.md,按顺序分流。修复轮
   上限取 plan.md frontmatter 的 `impl_fix_max_rounds`,字段缺失或非正
   整数一律按**默认 3**(取值规则与 rawf-implement 一致):
   - 存在 plan-blocker → 不进入修复。向用户完整转述该问题,由用户决定
     退回 /rawf-plan 重做方案,或人工处理。
   - fail 且 NN < 上限 → 进入 /rawf-implement 修复轮。
   - fail 且 NN ≥ 上限 → 停止修复。向用户汇报未决的问题清单,交人工判断。
   - pass → 进入汇报收尾(遗留 minor 一并带上)。
   用户中途明确要求追加修复轮数时,更新 plan.md 的 `impl_fix_max_rounds`
   并在下一轮实现记录中注明;不得未经用户提出而自行修改该字段。
3. 分流前先核对证据档位:评审须**按 plan 声明的档位**核验(定义见
   review-standards.md「测试证据档位」)。若评审**仅因无原始输出打回 C 档**
   用例,这属于可向用户申诉的误报——按第 4 条原样呈给用户裁决,不自行修改
   plan 的档位来迎合评审。
4. 认为评审有误报时,不得"解释掉"后静默忽略:原样呈给用户裁决,用户
   同意不修的,在下一轮实现记录或汇报中注明。
