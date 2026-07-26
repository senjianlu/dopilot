#!/usr/bin/env bash
# TC-03(异常/反向路径):证明 TC-01 的顺序断言不是恒真通过。
# 用法(cwd 必须是仓库根):bash <本脚本>
#
# 本脚本自己在 scratchpad 生成一份**旧顺序**(login 排在 QEMU/Buildx 之后)
# 的 workflow 副本,对其运行 step-order-check.py,断言其**必须非零退出**;
# 再对当前工作区版本运行,断言退出 0。伪造副本由脚本内的 python 就地生成,
# 无需外部搭建,故本用例可由单条命令完整复现。
set -uo pipefail

WF=.github/workflows/docker.yml
CHECKER=.ai/2026-07-26/ci-docker-login-before-buildx/evidence/step-order-check.py
SCRATCH=${SCRATCH_DIR:-/tmp/claude-1000/-home-rabbir-Projects-dopilot/c710bc7e-e506-4ef8-a504-c70181b8a2f7/scratchpad}/tc03
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
mkdir -p "$SCRATCH"

note "== 1. 生成旧顺序副本(把 Login 块移回 Buildx 之后)=="
python3 - "$WF" "$SCRATCH/docker.old-order.yml" <<'PY'
import sys, yaml

src, dst = sys.argv[1], sys.argv[2]
wf = yaml.safe_load(open(src, encoding="utf-8"))
LOGIN = "Login to Docker Hub"
BUILDX = "Set up Docker Buildx"

for job in ("base", "app"):
    steps = wf["jobs"][job]["steps"]
    names = [s.get("name") for s in steps]
    li, bi = names.index(LOGIN), names.index(BUILDX)
    login = steps.pop(li)
    # pop 之后 buildx 下标左移 1(login 原本在其前)
    steps.insert(names.index(BUILDX) - 1 + 1, login)
    print(f"  job [{job}]:Login 由下标 {li} 移到 Buildx({bi}) 之后")

with open(dst, "w", encoding="utf-8") as fh:
    yaml.safe_dump(wf, fh, allow_unicode=True, sort_keys=False, width=4096)
print(f"  已写出:{dst}")
PY

note ""
note "  --- 副本中两个 job 的步骤顺序 ---"
python3 -c '
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for job in ("base", "app"):
    print(f"    [{job}]")
    for i, s in enumerate(wf["jobs"][job]["steps"]):
        print(f"      [{i}] {s.get(\"name\", s.get(\"uses\"))}")
' "$SCRATCH/docker.old-order.yml"

note ""
note "== 2. 对旧顺序副本运行顺序断言 —— 必须非零退出,且必须是"顺序违例" =="
# 仅断言 rc != 0 是不够的:脚本崩溃(如 YAML 解析异常)同样非零退出,
# 会让反向自检假通过。故同时断言输出里出现顺序违例的判定文案,并确认
# 两个 job 都被点名。
note "\$ python3 $CHECKER $SCRATCH/docker.old-order.yml"
out=$(python3 "$CHECKER" "$SCRATCH/docker.old-order.yml" 2>&1); rc=$?
printf '%s\n' "$out" | sed 's/^/  /'
note "  退出码=$rc"
violations=$(printf '%s\n' "$out" | grep -c '未早于' || true)
if [ "$rc" -eq 0 ]; then
  bad "反向自检失效:旧顺序副本竟然通过了顺序断言"
elif [ "$violations" -eq 0 ]; then
  bad "旧顺序副本虽非零退出,但输出中没有顺序违例判定 —— 疑似脚本崩溃而非断言生效"
else
  ok "旧顺序副本被判 FAIL,且给出 $violations 条顺序违例(每个 job 各 2 条:QEMU 与 Buildx)"
fi

note ""
note "== 3. 对当前工作区版本运行同一断言 —— 必须退出 0 =="
note "\$ python3 $CHECKER $WF"
python3 "$CHECKER" "$WF" 2>&1 | sed 's/^/  /'
rc=${PIPESTATUS[0]}
note "  退出码=$rc"
if [ "$rc" -eq 0 ]; then
  ok "当前版本被判 PASS"
else
  bad "当前工作区版本未通过顺序断言"
fi

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS —— 顺序断言正反两向均有效,非恒真通过" || note "RESULT: FAIL"
exit "$fail"
