#!/usr/bin/env bash
# TC-04:新版 gate-review.sh(Stop hook)三种锁状态的行为。
# 在 mktemp -d 的假项目里构造"第 01 轮实现已写、无评审文件"的状态,
# 以 CLAUDE_PROJECT_DIR 指向假项目调用本仓库的 hook。
set -uo pipefail
repo=$(git rev-parse --show-toplevel)
hook="$repo/.claude/hooks/gate-review.sh"
fake=$(mktemp -d)
trap '[ -n "${holder:-}" ] && kill -- "-$holder" 2>/dev/null; rm -rf "$fake"' EXIT
td=.ai/2099-01-01/fake-task
mkdir -p "$fake/$td"
echo "$td" > "$fake/.ai/.current-task"
printf -- '---\nstatus: approved\n---\n' > "$fake/$td/plan.md"
echo '# 实现记录' > "$fake/$td/implementation-round-01.md"
fail=0

run_hook() { echo '{}' | CLAUDE_PROJECT_DIR="$fake" bash "$hook"; }

echo "== 情形 1:无锁文件 → 期望 block =="
out=$(run_hook); rc=$?
echo "rc=$rc out=$out"
if [ $rc -eq 0 ] && printf '%s' "$out" | jq -e '.decision == "block"' >/dev/null; then echo "PASS 情形 1"; else echo "FAIL 情形 1"; fail=1; fi

echo "== 情形 2:.review-lock 被 flock 持有 → 期望无输出放行 =="
touch "$fake/$td/.review-lock"
# -o:锁由 flock 进程自身持有、不传给 sleep;setsid 自成进程组,便于整组终止
setsid flock -o "$fake/$td/.review-lock" sleep 30 &
holder=$!
for _ in $(seq 1 50); do
  flock -n -E 75 "$fake/$td/.review-lock" true 2>/dev/null; [ $? -eq 75 ] && break; sleep 0.1
done
out=$(run_hook); rc=$?
echo "rc=$rc out='$out'"
if [ $rc -eq 0 ] && [ -z "$out" ]; then echo "PASS 情形 2"; else echo "FAIL 情形 2"; fail=1; fi
kill -- "-$holder" 2>/dev/null; wait "$holder" 2>/dev/null; holder=

echo "== 情形 2b:锁文件存在但未被持有 → 期望 block =="
out=$(run_hook); rc=$?
echo "rc=$rc out=$out"
if [ $rc -eq 0 ] && printf '%s' "$out" | jq -e '.decision == "block"' >/dev/null; then echo "PASS 情形 2b"; else echo "FAIL 情形 2b"; fail=1; fi

echo "== 情形 3:.review-lock 是目录(旧版残留)→ 期望仍 block(fail-closed)=="
rm -f "$fake/$td/.review-lock"; mkdir "$fake/$td/.review-lock"
out=$(run_hook); rc=$?
echo "rc=$rc out=$out"
if [ $rc -eq 0 ] && printf '%s' "$out" | jq -e '.decision == "block"' >/dev/null; then echo "PASS 情形 3"; else echo "FAIL 情形 3"; fail=1; fi

echo "== 情形 4:已有本轮评审文件 → 期望放行 =="
rmdir "$fake/$td/.review-lock"; echo x > "$fake/$td/review-round-01-pass.md"
out=$(run_hook); rc=$?
echo "rc=$rc out='$out'"
if [ $rc -eq 0 ] && [ -z "$out" ]; then echo "PASS 情形 4"; else echo "FAIL 情形 4"; fail=1; fi

echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
