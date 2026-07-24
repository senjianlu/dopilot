#!/usr/bin/env python3
"""TC-01: verify every relative markdown link under docs/ and the root-level
markdown files resolves to an existing file. Prints offending links, or
'ALL LINKS OK'; exit 0 iff none are broken."""
import re
import sys
import pathlib

root = pathlib.Path("/workspaces/dopilot")
targets = list(root.glob("docs/**/*.md")) + [
    root / "README.md",
    root / "README.zh-CN.md",
    root / "CONTRIBUTING.md",
    root / "AGENTS.md",
    root / "CLAUDE.md",
]
bad = []
for md in targets:
    for m in re.finditer(r"\]\(([^)#\s]+)\)", md.read_text()):
        link = m.group(1)
        if link.startswith(("http", "mailto:")):
            continue
        if not (md.parent / link).resolve().exists():
            bad.append(f"{md.relative_to(root)} -> {link}")
if bad:
    print("\n".join(bad))
    sys.exit(1)
print("ALL LINKS OK")
