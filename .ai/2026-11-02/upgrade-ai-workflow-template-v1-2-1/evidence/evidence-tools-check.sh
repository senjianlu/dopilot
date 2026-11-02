#!/usr/bin/env bash
# TC-05:新增的 evidence.sh / evidence-check.sh 在假项目中的行为(含异常路径)。
# 假项目以 CLAUDE_PROJECT_DIR 指向,不写本仓库任何路径。
set -uo pipefail
repo=$(git rev-parse --show-toplevel)
ev="$repo/.ai-workflow/scripts/evidence.sh"
ck="$repo/.ai-workflow/scripts/evidence-check.sh"
fake=$(mktemp -d)
trap 'rm -rf "$fake"' EXIT
git -C "$fake" init -q && git -C "$fake" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m init
td=.ai/2099-01-01/fake-task
mkdir -p "$fake/$td/evidence"
echo "$td" > "$fake/.ai/.current-task"
export CLAUDE_PROJECT_DIR="$fake"
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }

echo "== evidence.sh:退出码透传与头尾字段 =="
bash "$ev" TC-01 -- bash -c 'echo hello; echo to-stderr >&2; exit 7'; rc=$?
[ $rc -eq 7 ] && ok "退出码透传 7" || bad "退出码 $rc ≠ 7"
f="$fake/$td/evidence/TC-01.log"
echo "--- TC-01.log ---"; cat "$f"; echo "--- /TC-01.log ---"
[ "$(head -1 "$f")" = "# rawf-evidence v1" ] && ok "首行 rawf-evidence v1" || bad "首行不符"
for k in 'tc: TC-01' 'cmd: ' 'cwd: ' 'git_head: ' 'started: ' '--- output ---' '--- end ---' 'exit: 7' 'finished: ' 'bytes: '; do
  grep -qF -- "$k" "$f" && ok "含字段 '$k'" || bad "缺字段 '$k'"
done
grep -qx 'hello' "$f" && grep -qx 'to-stderr' "$f" && ok "stdout 与 stderr 均已收录" || bad "输出收录不全"

echo "== evidence.sh:同名二次运行须拒绝覆盖(exit 3)=="
before=$(sha256sum < "$f")
bash "$ev" TC-01 -- true; rc=$?
[ $rc -eq 3 ] && ok "同名重跑 exit 3" || bad "同名重跑 exit $rc"
[ "$(sha256sum < "$f")" = "$before" ] && ok "原证据未被改动" || bad "原证据被改动"

echo "== evidence.sh:非法 TC 编号 exit 3 =="
bash "$ev" BAD-01 -- true; rc=$?
[ $rc -eq 3 ] && ok "非法编号 exit 3" || bad "非法编号 exit $rc"

echo "== evidence-check.sh:完整假任务 → exit 0 =="
bash "$ev" TC-02 -- bash -c 'echo fine' >/dev/null 2>&1
cat > "$fake/$td/plan.md" <<'EOF'
---
status: approved
task: fake-task
date: 2099-01-01
approved_at: 2099-01-01 00:00:00+0000
evidence_format: v1
---

# 方案:假任务

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 无 | 跑命令 | exit 7 | evidence/TC-01.log |
| TC-02 | A | 无 | 跑命令 | exit 0 | evidence/TC-02.log |
EOF
cat > "$fake/$td/implementation-round-01.md" <<'EOF'
---
task: fake-task
round: 01
date: 2099-01-01
---

# 实现记录:第 01 轮

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | TC-01.log |
| TC-02 | A | pass | TC-02.log |
EOF
bash "$ck"; rc=$?
[ $rc -eq 0 ] && ok "完整记录 evidence-check exit 0" || bad "完整记录 evidence-check exit $rc"

echo "== evidence-check.sh:实现记录缺 TC-02 行 → 非零 =="
sed -i '/^| TC-02 |/d' "$fake/$td/implementation-round-01.md"
out=$(bash "$ck" 2>&1); rc=$?
printf '%s\n' "$out"
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'MISSING-ROW' && ok "缺行 → exit $rc 且报 MISSING-ROW" || bad "缺行未被拦下(exit $rc)"

echo "== evidence-check.sh:证据被截断 → 非零 =="
printf '| TC-02 | A | pass | TC-02.log |\n' >> "$fake/$td/implementation-round-01.md"
sed -i 's/^bytes: .*/bytes: 99999/' "$fake/$td/evidence/TC-02.log"
out=$(bash "$ck" 2>&1); rc=$?
printf '%s\n' "$out"
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'TRUNCATED' && ok "bytes 不符 → exit $rc 且报 TRUNCATED" || bad "截断未被拦下(exit $rc)"

echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
