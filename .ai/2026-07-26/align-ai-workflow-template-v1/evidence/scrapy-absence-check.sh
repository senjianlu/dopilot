#!/usr/bin/env bash
# TC-03:Scrapy 标准栈"三处联动缺席"断言 + 反向自检。
# 三处必须同去同留:AGENTS.md 技术栈章节 / review-standards.md 评审关注点 /
# rawf-stack-scrapy skill。任一处残留即失败(半套残留会误导评审与开发)。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail

AGENTS=AGENTS.md
STD=.ai-workflow/review-standards.md
SKILL=.claude/skills/rawf-stack-scrapy
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

# has_agents_scrapy <file>:0=检出残留 1=干净
has_agents_scrapy() {
  grep -qE '^###[[:space:]]+爬虫' "$1" && return 0
  grep -qE 'scrapyd-client|TWISTED_REACTOR' "$1" && return 0
  return 1
}
# has_std_scrapy <file>:0=检出残留 1=干净
has_std_scrapy() {
  grep -qE '^-[[:space:]]*Scrapy[::]' "$1"
}

note "== 1. AGENTS.md 无「### 爬虫」章节、无 scrapyd-client / TWISTED_REACTOR =="
if has_agents_scrapy "$AGENTS"; then
  grep -nE '^###[[:space:]]+爬虫|scrapyd-client|TWISTED_REACTOR' "$AGENTS" | sed 's/^/  /'
  bad "AGENTS.md 存在 Scrapy 栈残留"
else
  ok "ABSENT —— AGENTS.md 无 Scrapy 栈章节(D-3)"
fi

note ""
note "== 2. review-standards.md 无 Scrapy 评审关注点行 =="
if has_std_scrapy "$STD"; then
  grep -nE '^-[[:space:]]*Scrapy[::]' "$STD" | sed 's/^/  /'
  bad "review-standards.md 存在 Scrapy 关注点残留"
else
  note "  现存技术栈关注点:"
  sed -n '/^## 技术栈评审关注点/,$p' "$STD" | grep '^- ' | sed 's/^/    /'
  ok "ABSENT —— review-standards.md 无 Scrapy 关注点(D-1)"
fi

note ""
note "== 3. .claude/skills/rawf-stack-scrapy 路径不存在 =="
if [ -e "$SKILL" ]; then
  bad "$SKILL 存在(Scrapy 栈 skill 回流)"
else
  note "  现存 rawf skills:"
  ls -1 .claude/skills | sed 's/^/    /'
  ok "ABSENT —— 无 rawf-stack-scrapy skill(D-4)"
fi

note ""
note "== 4. 反向自检:向副本注入残留必须被检出 =="
SCRATCH=${SCRATCH_DIR:-/tmp/claude-1000/-home-rabbir-Projects-dopilot/c710bc7e-e506-4ef8-a504-c70181b8a2f7/scratchpad}
mkdir -p "$SCRATCH/tc03"

cp "$STD" "$SCRATCH/tc03/review-standards.injected.md"
printf -- '- Scrapy:阻塞调用混入 reactor/事件循环、selector 取值无防御\n' >> "$SCRATCH/tc03/review-standards.injected.md"
if has_std_scrapy "$SCRATCH/tc03/review-standards.injected.md"; then
  ok "注入 '- Scrapy:' 关注点行 -> 被检出(检测函数有效)"
else
  bad "注入残留未被检出,review-standards.md 的检测恒真通过"
fi

cp "$AGENTS" "$SCRATCH/tc03/AGENTS.injected.md"
printf '\n### 爬虫\n\n| 打包 | scrapyd-client | 2.x |\n' >> "$SCRATCH/tc03/AGENTS.injected.md"
if has_agents_scrapy "$SCRATCH/tc03/AGENTS.injected.md"; then
  ok "注入「### 爬虫」章节 -> 被检出(检测函数有效)"
else
  bad "注入残留未被检出,AGENTS.md 的检测恒真通过"
fi

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS —— 三处同时缺席,且检测函数经反向自检有效" || note "RESULT: FAIL"
exit "$fail"
