#!/usr/bin/env bash
# TC-06:用真实历史试跑改写(不碰本仓库与远端)。
# 克隆本仓库 → 把当前工作区(已跟踪 + 新增、排除未跟踪的建议目录与 gitignore)同步进
# 克隆并提交 → rewrite_history run + verify。只打印统计与核验结论。
set -uo pipefail
repo=$(git rev-parse --show-toplevel); cd "$repo" || exit 3
sugg=.ai/2026-11-02/transient-failures-permanent-disable
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git clone -q --no-hardlinks "$repo" "$tmp/clone" || exit 3

# 同步工作区:以本仓库"已跟踪 ∪ 未跟踪未忽略"为准,排除建议目录
( git ls-files -z --cached --others --exclude-standard | tr '\0' '\n' \
    | grep -v -E "^$sugg/" ) > "$tmp/want.txt"
while IFS= read -r p; do
  [ -f "$p" ] || continue
  mkdir -p "$tmp/clone/$(dirname "$p")"; cp -p "$p" "$tmp/clone/$p"
done < "$tmp/want.txt"
( cd "$tmp/clone" && git ls-files ) | while IFS= read -r p; do
  [ -e "$repo/$p" ] && grep -qxF -- "$p" "$tmp/want.txt" || rm -f "$tmp/clone/$p"
done
git -C "$tmp/clone" add -A
git -C "$tmp/clone" -c user.name=dry-run -c user.email=dry-run@example.com \
  -c core.hooksPath=/dev/null commit -q -m "chore(repo): redaction dry run" || exit 3
echo "克隆提交数:$(git -C "$tmp/clone" rev-list --count master)"

python3 scripts/redaction/rewrite_history.py run --src "$tmp/clone" --dst "$tmp/new.git" --ref master || exit 1
python3 scripts/redaction/rewrite_history.py verify --src "$tmp/clone" --dst "$tmp/new.git" --ref master
vrc=$?

# rawf-evidence v1 证据在改写后仍结构有效:git_head 已映射为新库中存在的提交,bytes 仍等于正文字节数
python3 - "$tmp/new.git" <<'PY'
import re, subprocess, sys
dst = sys.argv[1]
task = ".ai/2026-11-02/upgrade-ai-workflow-template-v1-2-1/evidence/"
names = [n for n in subprocess.run(["git", "-C", dst, "ls-tree", "--name-only", f"master:{task}"],
         capture_output=True, text=True, check=True).stdout.split() if n.endswith(".log")]
bad = 0
for n in names:
    b = subprocess.run(["git", "-C", dst, "show", f"master:{task}{n}"], capture_output=True,
                       check=True).stdout
    head_end = b.index(b"--- output ---\n") + len(b"--- output ---\n")
    foot = b.rindex(b"\n--- end ---\n")
    declared = int(re.search(rb"\nbytes: (\d+)\n", b[foot:]).group(1))
    gh = re.search(rb"\ngit_head: ([0-9a-f]{40})", b[:head_end]).group(1).decode()
    exists = subprocess.run(["git", "-C", dst, "cat-file", "-e", f"{gh}^{{commit}}"]).returncode == 0
    ok = b.startswith(b"# rawf-evidence v1\n") and declared == foot - head_end and exists
    bad += not ok
    print(f"  {'OK ' if ok else 'BAD'} {n}: bytes {declared} / 正文 {foot - head_end};git_head 在改写后的库中{'存在' if exists else '不存在'}")
print(("PASS  " if not bad and len(names) == 8 else "FAIL  ") + f"v1 证据 {len(names)} 个改写后结构有效(异常 {bad})")
sys.exit(1 if bad or len(names) != 8 else 0)
PY
erc=$?

# 机制文件(含测试夹具)在改写前后逐字节相同:规则不得改动工具自身与测试语义
mrc=0
diffs=$(git -C "$tmp/clone" ls-tree -r master -- scripts/redaction .githooks | sort)
newd=$(git -C "$tmp/new.git" ls-tree -r master -- scripts/redaction .githooks | sort)
n=$(printf '%s\n' "$diffs" | sed '/^$/d' | wc -l)
if [ "$diffs" = "$newd" ] && [ "$n" -gt 0 ]; then echo "PASS  scripts/redaction 与 .githooks 共 $n 个文件改写前后 blob 完全相同"
else echo "FAIL  机制文件在改写后发生变化"; mrc=1; fi

[ "$vrc" -eq 0 ] && [ "$erc" -eq 0 ] && [ "$mrc" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
