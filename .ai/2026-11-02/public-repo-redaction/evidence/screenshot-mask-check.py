#!/usr/bin/env python3
"""TC-11:真实截图的打码核验(不输出任何图像内容,只输出哈希与像素统计)。

1) 工作区 PNG = 私有打码文件(sha256);2) HEAD 中该路径的原 blob id = 私有规则 blob 条目;
3) 尺寸不变;4) 8 个遮盖矩形以外逐像素与原图相同,矩形以内为单一填充色。
"""
import hashlib, io, os, subprocess, sys
from pathlib import Path
from PIL import Image

PATH = ".ai/2026-09-16/fix-console-horizontal-overflow/evidence/schedules-after-fix.png"
PRIVATE = Path("~/.local/share/dopilot-private/schedules-after-fix.masked.png").expanduser()
FILL = (203, 213, 225)
ROWS = ((216, 246), (265, 295), (314, 344), (363, 393))
RECTS = [(x0, y0, x1, y1) for y0, y1 in ROWS for x0, x1 in ((300, 548), (766, 1012))]

repo = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                      text=True, check=True).stdout.strip()
os.chdir(repo)
sys.path.insert(0, "scripts/redaction")
import redact  # noqa: E402

fail = 0
def check(cond, msg):
    global fail
    print(("PASS  " if cond else "FAIL  ") + msg)
    fail |= not cond

work = Path(PATH).read_bytes()
priv = PRIVATE.read_bytes()
sha = lambda b: hashlib.sha256(b).hexdigest()
print(f"      工作区 sha256 = {sha(work)}")
print(f"      私有打码 sha256 = {sha(priv)}")
check(work == priv, "工作区 PNG 与私有打码文件逐字节相同")

head_oid = subprocess.run(["git", "rev-parse", f"HEAD:{PATH}"], capture_output=True,
                          text=True, check=True).stdout.strip()
blob_rules = [r for r in redact.load_rules() if r.kind == "blob"]
check(any(r.pattern == head_oid and Path(r.repl).expanduser() == PRIVATE for r in blob_rules),
      f"HEAD 原 blob {head_oid[:12]} 已登记为私有 blob 规则,替换物即该打码文件")

orig = Image.open(io.BytesIO(subprocess.run(["git", "show", f"HEAD:{PATH}"],
                  capture_output=True, check=True).stdout)).convert("RGB")
new = Image.open(io.BytesIO(work)).convert("RGB")
check(orig.size == new.size, f"尺寸不变:{orig.size}")
w, h = orig.size
po, pn = orig.load(), new.load()
inside = lambda x, y: any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in RECTS)
outside_diff = inside_bad = inside_n = 0
for y in range(h):
    for x in range(w):
        if inside(x, y):
            inside_n += 1
            if pn[x, y] != FILL:
                inside_bad += 1
        elif pn[x, y] != po[x, y]:
            outside_diff += 1
check(outside_diff == 0, f"矩形以外像素与原图差异 {outside_diff} 个")
check(inside_bad == 0, f"矩形以内 {inside_n} 个像素均为填充色 {FILL}(异常 {inside_bad})")
changed = sum(1 for y in range(h) for x in range(w) if inside(x, y) and po[x, y] != FILL)
check(changed > 0, f"矩形内原图有 {changed} 个非填充色像素被覆盖(遮盖确实生效)")
print("RESULT:", "FAIL" if fail else "PASS")
sys.exit(fail)
