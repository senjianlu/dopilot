#!/usr/bin/env bash
# TC-04:三份 compose 用新变量名渲染成功,且渲染结果正确。
# 断言:①解析退出码 0;②渲染结果不含任何裸旧名 key;③密码进入
# DOPILOT_REDIS_URL;④有 redis 服务的两份里 --requirepass 与 URL 同源。
# 不启容器(只跑 `docker compose config`)。
# 用法(cwd 必须是仓库根):bash <本脚本>
set -uo pipefail
export LC_ALL=C

D=deploy/docker
PASS_VAL=tc04-pass
HOST_VAL=tc04-host
fail=0
note() { printf '%s\n' "$*"; }
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { fail=1; printf 'FAIL  %s\n' "$*"; }

[ -f AGENTS.md ] && [ -d .ai-workflow ] || { echo "cwd 必须是 dopilot 仓库根" >&2; exit 2; }
command -v docker >/dev/null || { echo "找不到 docker" >&2; exit 2; }
note "docker compose 版本:$(docker compose version 2>&1 | head -1)"

render() { # render <compose-file>
  case "$1" in
    docker-compose.agent.yml)
      env -u DOPILOT_REDIS_URL -C "$D" \
        DOPILOT_REDIS_PASSWORD="$PASS_VAL" DOPILOT_REDIS_HOST="$HOST_VAL" \
        DOPILOT_AGENT_TOKEN=tc04-agent-token-1234567890 \
        DOPILOT_SERVER_URL=http://tc04-server:5000 \
        docker compose -f "$1" config 2>&1 ;;
    *)
      env -u DOPILOT_REDIS_URL -C "$D" \
        DOPILOT_REDIS_PASSWORD="$PASS_VAL" docker compose -f "$1" config 2>&1 ;;
  esac
}

for f in docker-compose.yml docker-compose.server.yml docker-compose.agent.yml; do
  note ""
  note "===== $f ====="
  out=$(render "$f"); rc=$?
  printf '%s\n' "$out" | sed 's/^/  /'
  note "  解析退出码=$rc"
  [ "$rc" -eq 0 ] && ok "$f 解析成功" || { bad "$f 解析失败"; continue; }

  if printf '%s\n' "$out" | grep -qE '^[[:space:]]*(AGENT_ID|AGENT_WORKDIR|REDIS_PASSWORD|REDIS_HOST):'; then
    printf '%s\n' "$out" | grep -nE '^[[:space:]]*(AGENT_ID|AGENT_WORKDIR|REDIS_PASSWORD|REDIS_HOST):' | sed 's/^/  HIT  /'
    bad "$f 渲染结果含裸旧名 key"
  else
    ok "$f 渲染结果无裸旧名 key"
  fi

  n=$(printf '%s\n' "$out" | grep -cE "DOPILOT_REDIS_URL: redis://:$PASS_VAL@")
  note "  DOPILOT_REDIS_URL 含注入密码的行数=$n"
  [ "$n" -ge 1 ] && ok "$f 密码已进入 Redis URL" || bad "$f 密码未进入 Redis URL"

  if [ "$f" != docker-compose.agent.yml ]; then
    printf '%s\n' "$out" | grep -q -- "- $PASS_VAL" \
      && ok "$f redis --requirepass 与 URL 同源(同一 DOPILOT_REDIS_PASSWORD)" \
      || bad "$f --requirepass 未取到同一密码"
  else
    printf '%s\n' "$out" | grep -q "DOPILOT_REDIS_URL: redis://:$PASS_VAL@$HOST_VAL:6379/0" \
      && ok "$f Redis URL 由 DOPILOT_REDIS_PASSWORD + DOPILOT_REDIS_HOST 正确拼出" \
      || bad "$f Redis URL 拼装不符预期"
    for k in DOPILOT_AGENT_ID DOPILOT_AGENT_WORKDIR; do
      printf '%s\n' "$out" | grep -q "$k:" && ok "$f 含 $k" || bad "$f 缺 $k"
    done
  fi
done

note ""
note "===== 一体栈 agent 身份逐个不同(每个 agent 必须有独立 id) ====="
ids=$(render docker-compose.yml | grep -E '^[[:space:]]*DOPILOT_AGENT_ID:' | awk '{print $2}' | sort)
printf '%s\n' "$ids" | sed 's/^/    /'
nid=$(printf '%s\n' "$ids" | wc -l); nuniq=$(printf '%s\n' "$ids" | sort -u | wc -l)
{ [ "$nid" -eq 3 ] && [ "$nuniq" -eq 3 ]; } \
  && ok "3 个 agent 的 DOPILOT_AGENT_ID 各不相同" \
  || bad "agent id 数量/唯一性不符预期(共 $nid 个,去重后 $nuniq 个)"

note ""
[ "$fail" -eq 0 ] && note "RESULT: PASS" || note "RESULT: FAIL"
exit "$fail"
