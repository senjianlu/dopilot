#!/usr/bin/env bash
# TC-05:证明 Login 块上移后,其引用的表达式仍能解析。
# 用法(cwd 必须是仓库根):bash <本脚本>
#
# 断言:
#   ① DOCKERHUB_USERNAME 定义在 **workflow 级 env**(而非 job/step 级)——
#      workflow 级 env 对该 workflow 内任意 job 的任意步骤可见,故 login 块
#      移到 job 内更靠前的位置不会解析不到值;
#   ② login 块不依赖任何 steps.* 输出(块内无 steps. 引用);
#   ③ 两个 job 中 login 仍排在 actions/checkout 之后(保持既有相对位置)。
set -uo pipefail

WF=.github/workflows/docker.yml
fail=0
note() { printf '%s\n' "$*"; }
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }

note "== 1. DOCKERHUB_USERNAME 的定义层级 =="
python3 - "$WF" <<'PY'
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))

top = wf.get("env", {}) or {}
print(f"  workflow 级 env keys: {sorted(top.keys())}")
if "DOCKERHUB_USERNAME" in top:
    print(f"  DOCKERHUB_USERNAME 定义于 workflow 级:{top['DOCKERHUB_USERNAME']}")
    print("  LEVEL=workflow")
else:
    print("  LEVEL=not-workflow")

for job_name, job in wf["jobs"].items():
    if "DOCKERHUB_USERNAME" in (job.get("env") or {}):
        print(f"  注意:job [{job_name}] 也有 job 级 env 定义")
PY
level=$(python3 -c '
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
print("workflow" if "DOCKERHUB_USERNAME" in (wf.get("env") or {}) else "other")
' "$WF")
if [ "$level" = workflow ]; then
  ok "DOCKERHUB_USERNAME 在 workflow 级 env,对 job 内任意位置的步骤可见"
else
  bad "DOCKERHUB_USERNAME 不在 workflow 级 env,上移 login 块可能解析不到值"
fi

note ""
note "== 2. login 块不依赖 steps.* 输出 =="
block=$(awk '/^      - name: Login to Docker Hub$/ {f=1} f {print; n++} n==5 {exit}' "$WF")
note "  块内容:"; printf '%s\n' "$block" | sed 's/^/    | /'
if printf '%s\n' "$block" | grep -q 'steps\.'; then
  bad "login 块引用了 steps.*,上移可能取不到前置步骤输出"
else
  ok "login 块只引用 env.* 与 secrets.*,不依赖任何步骤输出"
fi

note ""
note "== 3. 两个 job 中 login 仍在 checkout 之后 =="
python3 - "$WF" <<'PY'
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
bad = 0
for job in ("base", "app"):
    steps = wf["jobs"][job]["steps"]
    ck = next(i for i, s in enumerate(steps)
              if str(s.get("uses", "")).startswith("actions/checkout"))
    lg = next(i for i, s in enumerate(steps) if s.get("name") == "Login to Docker Hub")
    status = "OK  " if ck < lg else "FAIL"
    print(f"  {status} job [{job}]: checkout={ck}  login={lg}")
    if ck >= lg:
        bad = 1
sys.exit(bad)
PY
if [ $? -eq 0 ]; then
  ok "两个 job 均满足 checkout < login"
else
  bad "存在 login 排在 checkout 之前的 job"
fi

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
