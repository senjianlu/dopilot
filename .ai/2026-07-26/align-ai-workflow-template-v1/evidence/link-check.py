#!/usr/bin/env python3
"""TC-06:检查 markdown 文件中的相对链接目标是否存在。

用法(cwd 必须是仓库根):
    python3 <本脚本> <md 文件> [<md 文件> ...]

跳过 http(s)/mailto 等绝对链接与纯锚点(#...);其余按"相对于该 md 所在目录"
解析,目标不存在即报 BROKEN。退出码:0=无 BROKEN,1=存在 BROKEN。
"""

import re
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#")


def main(argv: list[str]) -> int:
    if not argv:
        print("用法:python3 link-check.py <md 文件> [...]", file=sys.stderr)
        return 2

    broken = 0
    checked = 0
    for name in argv:
        md = Path(name)
        if not md.is_file():
            print(f"BROKEN  {name} -> 待检查的 md 文件本身不存在")
            broken += 1
            continue
        print(f"== {name} ==")
        for raw in LINK.findall(md.read_text(encoding="utf-8")):
            target = raw.split(" ")[0].strip()
            if target.startswith(SKIP_PREFIX):
                print(f"  SKIP    {target}")
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                print(f"  SKIP    {target}(纯锚点)")
                continue
            resolved = (md.parent / path_part).resolve()
            checked += 1
            if resolved.exists():
                print(f"  OK      {target} -> {resolved}")
            else:
                print(f"  BROKEN  {target} -> {resolved}")
                broken += 1

    print()
    print(f"相对链接检查数:{checked},BROKEN:{broken}")
    print("RESULT: PASS" if broken == 0 else "RESULT: FAIL")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
