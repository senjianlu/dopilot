#!/usr/bin/env bash
# TC-02:证明本次改动是**纯步骤换序**——没有任何一行被增、删或改写。
# 用法(cwd 必须是仓库根):bash <本脚本>
#
# 三项断言:
#   ① 改前(HEAD)与改后(工作区)两版**逐行排序后完全相同** —— 行的多重集
#      不变,意味着只可能是顺序变化;任何一行的增删改都会破坏这一等式;
#   ② 每个 job 的步骤名多重集相同 —— 步骤没有被增删;
#   ③ Login 块的 5 行在两版中逐字节一致 —— 移动过程没带进缩进/字符漂移。
set -uo pipefail

WF=.github/workflows/docker.yml
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
[ -f "$WF" ] || { echo "找不到 $WF" >&2; exit 2; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git show "HEAD:$WF" > "$tmp/before.yml" || { echo "无法取 HEAD 版本" >&2; exit 2; }
cp "$WF" "$tmp/after.yml"

note "== 0. 两版行数 =="
note "  改前(HEAD): $(wc -l < "$tmp/before.yml") 行"
note "  改后(工作区): $(wc -l < "$tmp/after.yml") 行"

note ""
note "== 1. 逐行排序后比对(行多重集必须完全相同)=="
sort "$tmp/before.yml" > "$tmp/before.sorted"
sort "$tmp/after.yml"  > "$tmp/after.sorted"
if diff -q "$tmp/before.sorted" "$tmp/after.sorted" >/dev/null; then
  ok "两版逐行排序后完全相同 —— 纯换序,无任何行被增删改"
else
  bad "两版行多重集不同 —— 存在被增删改的行:"
  diff -u "$tmp/before.sorted" "$tmp/after.sorted" | sed 's/^/    /'
fi

note ""
note "== 2. 每个 job 的步骤名多重集比对 =="
step_names() {
  python3 -c '
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for s in wf["jobs"][sys.argv[2]]["steps"]:
    print(s.get("name", "<uses:%s>" % s.get("uses")))
' "$1" "$2"
}
for job in base app; do
  a=$(step_names "$tmp/before.yml" "$job" | sort)
  b=$(step_names "$tmp/after.yml" "$job" | sort)
  if [ "$a" = "$b" ]; then
    ok "job [$job] 步骤名多重集不变($(printf '%s\n' "$b" | grep -c .) 步)"
  else
    bad "job [$job] 步骤集合发生变化:"
    diff <(printf '%s\n' "$a") <(printf '%s\n' "$b") | sed 's/^/    /'
  fi
done

note ""
note "== 3. Login 块逐字节比对 =="
login_block() {
  awk '/^      - name: Login to Docker Hub$/ {f=1} f {print; n++} n==5 {exit}' "$1"
}
login_block "$tmp/before.yml" > "$tmp/login.before"
login_block "$tmp/after.yml"  > "$tmp/login.after"
note "  改前块:"; sed 's/^/    | /' "$tmp/login.before"
note "  改后块:"; sed 's/^/    | /' "$tmp/login.after"
if [ ! -s "$tmp/login.after" ]; then
  bad "改后版本中找不到 Login 块"
elif cmp -s "$tmp/login.before" "$tmp/login.after"; then
  ok "Login 块 5 行逐字节一致,移动过程无内容漂移"
else
  bad "Login 块内容发生变化:"
  diff -u "$tmp/login.before" "$tmp/login.after" | sed 's/^/    /'
fi

note ""
note "== 4. 实际发生的位置变化(供人工过目)=="
diff -u "$tmp/before.yml" "$tmp/after.yml" | sed 's/^/  /'

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS —— 改动为纯步骤换序" || note "RESULT: FAIL"
exit "$fail"
