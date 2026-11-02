#!/usr/bin/env bash
# TC-10:公开引用范围与本地未推送引用审计(只打印引用名与计数)。
# 用户裁决 2026-11-02:本地未推送引用只断言私有业务规则零命中;通用规则(内网 IP)
# 命中均为早期代码/文档的示例地址,只打印数量。
set -uo pipefail
repo=$(git rev-parse --show-toplevel); cd "$repo" || exit 3
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }

remote_refs=$(git ls-remote origin | awk '{print $2}' | sort)
echo "远端引用:"; printf '  %s\n' $remote_refs
[ "$remote_refs" = "$(printf 'HEAD\nrefs/heads/master')" ] && ok "远端只有 HEAD 与 refs/heads/master(无标签、无 PR 引用)" || bad "远端存在 master 以外的引用"

local_only="refs/heads/feat/phase-0-skeleton refs/heads/chore/dev-toolchain-mcp-playwright refs/heads/worktree-logo-asset refs/original/refs/heads/feat/phase-0-skeleton refs/tags/backup/pre-normalize"
all_local=$(git for-each-ref --format='%(refname)' | grep -v -E '^refs/(remotes/|heads/master$|stash$)' | sort)
[ "$all_local" = "$(printf '%s\n' $local_only | sort)" ] && ok "本地 master 以外的引用恰为 5 个未推送引用" || { bad "本地引用清单不符"; printf '  %s\n' $all_local; }
total=0
for r in $local_only; do
  n=$(git rev-list --count "$r" --not master)
  total=$((total + n))
  out=$(python3 scripts/redaction/redact.py check --range "master..$r" --summary 2>&1)
  priv=$(printf '%s\n' "$out" | awk -F': ' '/^  private#/ {s += $2} END {print s + 0}')
  gen=$(printf '%s\n' "$out" | awk -F': ' '/^  generic#/ {s += $2} END {print s + 0}')
  echo "  $r:独有提交 $n 个;$(printf '%s\n' "$out" | grep '^redaction: scanned' | head -1);私有业务规则命中 $priv,通用规则命中 $gen"
  [ "$priv" -eq 0 ] && ok "$r 独有提交私有业务规则零命中" || bad "$r 独有提交有业务规则命中"
done
all=$(git rev-list --count --all); m=$(git rev-list --count master)
echo "  --all 可达 $all 个提交,master $m 个,本地独有合计 $total 个(各引用独有部分可能重叠)"
uniq_local=$(git rev-list --count $local_only --not master)
[ "$uniq_local" -eq $((all - m)) ] && ok "--all 中 master 以外的 $uniq_local 个提交全部属于这 5 个引用" || bad "存在不属于已知引用的提交"
echo
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
