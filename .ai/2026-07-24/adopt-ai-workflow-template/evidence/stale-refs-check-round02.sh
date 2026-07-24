#!/usr/bin/env bash
# TC-03: assert the repo contains no CURRENT references to the deleted docs
# trees (docs/dopilot|agent-governance|phases|refactor). Whitelisted lines are
# the intentional historical mentions (written with an explicit "git 历史可查"
# framing) plus code comments already tagged "git history:".
# Prints unexpected matches and RESULT line; exit 0 iff none found.
set -uo pipefail
cd /workspaces/dopilot

matches=$(grep -rn \
    --include='*.md' --include='*.py' --include='*.ts' --include='*.tsx' \
    --include='*.yml' --include='*.toml' --include='*.sh' --include='*.json' \
    -E 'docs/(dopilot|agent-governance|phases|refactor)' . \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.ai \
  | grep -v 'git history:' \
  | grep -vE '^(\./)?(docs/README\.md|docs/decisions/0018-adopt-ai-workflow-template\.md|docs/decisions/README\.md|docs/decisions/0008-redis-streams-agent-communication\.md|docs/architecture/03-execution-and-logs\.md):' \
  || true)

if [ -n "$matches" ]; then
  echo "$matches"
  echo "RESULT: FOUND UNEXPECTED REFS (fail)"
  exit 1
fi
echo "RESULT: NO UNEXPECTED REFS (pass)"
exit 0
