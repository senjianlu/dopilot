#!/usr/bin/env bash
# TC-05:当前树脱敏结果的一致性(只打印计数与别名侧路径,不回显任何真实业务词)。
#  1) apply-tree 再跑一遍零改动(幂等);2) selftest 0 problem;
#  3) 说明桩文件数 = 20 且逐个等于 stub-text(reason);
#  4) C 节正文类改动全部是"规则驱动":HEAD 版本经 redact 改写后与工作区逐字节相等;
#  5) 被改名的 2 个证据文件:新路径存在、为说明桩,所在任务正文中 evidence/ 引用全部可解析。
set -uo pipefail
repo=$(git rev-parse --show-toplevel); cd "$repo" || exit 3
R=scripts/redaction/redact.py
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }

out=$(python3 "$R" apply-tree 2>&1); echo "      apply-tree 第二遍:$out"
[ "$out" = "redaction: stubbed 0, replaced 0 binary, rewrote 0 text, renamed 0" ] && ok "apply-tree 幂等(第二遍零改动)" || bad "apply-tree 非幂等"
out=$(python3 "$R" selftest 2>&1); echo "      selftest:$out"
case "$out" in *", 0 problem(s)") ok "selftest 无问题" ;; *) bad "selftest 报问题" ;; esac

python3 - "$R" <<'PY' || fail=1
import subprocess, sys, importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("redact", sys.argv[1])
redact = importlib.util.module_from_spec(spec); sys.modules["redact"] = redact
spec.loader.exec_module(redact)
rules = redact.load_rules()
stubs = [r for r in rules if r.kind == "stub"]
bad = 0
def ok(m): print("PASS  " + m)
def no(m):
    global bad; bad = 1; print("FAIL  " + m)

# 改名映射:HEAD 中的旧路径 -> 工作区新路径(取 git 的 rename 检测,只打印新路径)
st = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=no"],
                    capture_output=True).stdout.split(b"\0")
renames, i = {}, 0
while i < len(st):
    rec = st[i].decode()
    if rec[:1] == "R":
        renames[st[i + 1].decode()] = rec[3:]
        i += 2
    else:
        i += 1
print(f"      已暂存改名:{len(renames)} 个 → " + ", ".join(sorted(renames.values())))
(ok if len(renames) == 2 else no)(f"改名文件数 = 2(实际 {len(renames)})")

# 说明桩:按 HEAD 路径匹配规则,检查工作区对应文件
head = subprocess.run(["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
                      capture_output=True).stdout.decode().split("\0")
stubbed = [p for p in head if p and redact.stub_reason(p, stubs)]
mism = 0
for p in stubbed:
    cur = Path(renames.get(p, p))
    want = redact.stub_text(redact.stub_reason(p, stubs)).encode()
    if not cur.is_file() or cur.read_bytes() != want:
        mism += 1
(ok if len(stubbed) == 20 and mism == 0 else no)(
    f"说明桩 {len(stubbed)} 个(期望 20),内容不符 {mism} 个")
for old, new in renames.items():
    (ok if old in stubbed else no)(f"改名文件 {new} 属于说明桩")

# 规则驱动:除说明桩、二进制与 B 表人工编辑文件外,每个改动文件 = HEAD 版本经规则改写
manual = {"AGENTS.md", "CONTRIBUTING.md", "pyproject.toml", "docs/README.md",
          "docs/decisions/README.md",
          "docs/decisions/0020-ai-workflow-template-version-anchor.md",
          "docs/architecture/README.md"}
changed = subprocess.run(["git", "diff", "--name-only", "-z", "--no-renames", "HEAD",
                          "--diff-filter=M"], capture_output=True).stdout.decode().split("\0")
checked = drift = 0
for p in changed:
    if not p or p in manual or p in stubbed:
        continue
    old = subprocess.run(["git", "show", f"HEAD:{p}"], capture_output=True).stdout
    if redact.is_binary(old):
        continue
    checked += 1
    if redact.encode(redact.rewrite_text(redact.decode(old), rules)) != Path(p).read_bytes():
        drift += 1
        print(f"      非规则驱动的改动:{p}")
(ok if checked == 31 and drift == 0 else no)(
    f"正文改动全部由规则产生:检查 {checked} 个(期望 31),偏离 {drift} 个")

# 被改名文件所在任务目录:正文中 evidence/<文件> 引用全部可解析
import re
dirs = {str(Path(n).parent.parent) for n in renames.values()}
refs = missing = 0
for d in dirs:
    for f in Path(d).rglob("*"):
        if f.is_file() and f.suffix in (".md", ".txt") and not redact.is_binary(f.read_bytes()):
            for m in re.finditer(r"evidence/([A-Za-z0-9._-]+\.(?:txt|md|log|png|py))", f.read_text(errors="replace")):
                refs += 1
                if not (Path(d) / "evidence" / m.group(1)).exists():
                    missing += 1
                    print(f"      断链:{f}: evidence/{m.group(1)}")
(ok if missing == 0 else no)(f"改名所在任务目录内 evidence/ 引用 {refs} 处,断链 {missing} 处")
sys.exit(bad)
PY

echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
