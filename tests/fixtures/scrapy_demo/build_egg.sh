#!/usr/bin/env bash
#
# Build the dopilot phase-1 demo Scrapy egg deterministically and place it at
#   tests/fixtures/scrapy_demo/eggs/demo_phase1.egg
#
# Usage:
#   tests/fixtures/scrapy_demo/build_egg.sh [PYTHON]
#
# PYTHON defaults to the repo venv interpreter. Requires scrapy + setuptools
# to be importable by that interpreter, e.g.:
#   .venv/bin/pip install 'scrapy>=2.11,<3' 'scrapyd>=1.4,<2'
#
# The egg is committed to git (eggs/ is intentionally NOT under dist/, which is
# .gitignore'd). The compose smoke and automated tests consume this egg.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${1:-${HERE}/../../../.venv/bin/python}"
EGG_DIR="${HERE}/eggs"
EGG_OUT="${EGG_DIR}/demo_phase1.egg"

cd "${HERE}"

# Clean any prior build state so the egg is reproducible.
rm -rf build dist demo.egg-info

# Build the egg. ``bdist_egg`` produces dist/demo-1.0-pyX.Y.egg.
"${PYTHON}" setup.py clean --all >/dev/null 2>&1 || true
"${PYTHON}" setup.py bdist_egg

mkdir -p "${EGG_DIR}"
BUILT="$(ls -1 dist/*.egg | head -n1)"
cp -f "${BUILT}" "${EGG_OUT}"

# Clean build byproducts so the working tree has no leftover artifacts.
rm -rf build dist demo.egg-info

echo "Built egg: ${EGG_OUT}"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${EGG_OUT}"
else
    "${PYTHON}" - "${EGG_OUT}" <<'PY'
import hashlib, sys
p = sys.argv[1]
print(hashlib.sha256(open(p, "rb").read()).hexdigest(), p)
PY
fi
