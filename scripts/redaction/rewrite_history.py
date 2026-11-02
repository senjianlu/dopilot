#!/usr/bin/env python3
"""Rewrite git history with the redaction rules (stdlib only, Python >= 3.10).

Policy: docs/decisions/0024-public-repo-redaction.md. Mechanism only -- the
business terms come from the private rules file (see redact.py).

    rewrite_history.py run    --src REPO --dst NEW.git --ref R [--ref R ...]
    rewrite_history.py verify --src REPO --dst NEW.git --ref R [--ref R ...]

Only the refs named with --ref are exported (default: master); every other
ref of SRC is left alone. SRC is never modified; DST must not exist.

run:    first checks every commit reachable from the refs: if two different
        paths of one tree would map to the same new path, it refuses
        (exit 1, DST not created). Then git fast-export -> filter ->
        git fast-import into DST. The filter
          * applies text rules to every text blob and commit/tag message,
          * replaces whole files matched by `stub` rules with the stub notice,
          * replaces blobs named by `blob` rules with the given local file,
          * applies text rules to every path (renames sensitive file names),
          * rewrites references to this repo's own commits -- any 7..40 hex
            token that is a unique prefix of an already-rewritten original
            commit -- to the new commit id of the same length (old ids would
            keep pointing at unredacted commits the host may still serve),
          * inside one commit, drops a delete/rename that path mapping turned
            into a no-op on a path the same commit writes (the redaction
            commit's own `git mv`); real collisions were refused up front.
        Writes DST/redaction-commit-map.tsv (old<TAB>new). DST must live
        outside the work tree: the map links old and new ids.
verify: for every commit reachable from the refs: mapped, same parents
        (mapped), identical author/committer lines, message == transformed
        message, and the WHOLE tree (paths, modes, contents) == the source
        tree under the same transform; annotated tag messages likewise; refs
        point at the mapped objects; DST has no detect-rule hit anywhere and
        no leftover old commit id.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redact  # noqa: E402

HEX = re.compile(rb"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")


# --------------------------------------------------------------------------
# C-style path quoting used by fast-export / fast-import
# --------------------------------------------------------------------------
_ESC = {b"n": b"\n", b"t": b"\t", b'"': b'"', b"\\": b"\\", b"a": b"\a",
        b"b": b"\b", b"f": b"\f", b"r": b"\r", b"v": b"\v"}


def unquote(p: bytes) -> bytes:
    if not (p.startswith(b'"') and p.endswith(b'"')):
        return p
    s, out, i = p[1:-1], bytearray(), 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\":
            n = s[i + 1:i + 2]
            if n in _ESC:
                out += _ESC[n]
                i += 2
            else:                                   # \ooo octal
                out.append(int(s[i + 1:i + 4], 8))
                i += 4
        else:
            out += c
            i += 1
    return bytes(out)


def quote(p: bytes) -> bytes:
    if not any(b in p for b in (b'"', b"\\", b"\n", b" ")) and all(
            32 <= ch < 127 for ch in p):
        return p
    out = bytearray(b'"')
    for ch in p:
        if ch in (0x22, 0x5C):
            out += b"\\" + bytes([ch])
        elif ch == 0x0A:
            out += b"\\n"
        elif 32 <= ch < 127:
            out.append(ch)
        else:
            out += b"\\%03o" % ch
    return bytes(out + b'"')


def git_out(repo: str, *a: str) -> bytes:
    return subprocess.run(["git", "-C", repo, *a], check=True,
                          capture_output=True).stdout


def cat(repo: str, oids) -> dict[str, bytes]:
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        return redact.cat_blobs(sorted(set(oids)))
    finally:
        os.chdir(cwd)


def ls_tree(repo: str, rev: str) -> dict[bytes, tuple[str, str]]:
    res = {}
    for rec in git_out(repo, "ls-tree", "-r", "-z", rev).split(b"\0"):
        if rec:
            meta, p = rec.split(b"\t", 1)
            mode, _typ, oid = meta.split()
            res[p] = (mode.decode(), oid.decode())
    return res


# --------------------------------------------------------------------------
class Rewriter:
    def __init__(self, rules, src: str):
        self.rules = rules
        self.stub_rules = [r for r in rules if r.kind == "stub"]
        self.blob_map = {r.pattern: Path(r.repl).expanduser().read_bytes()
                         for r in rules if r.kind == "blob"}
        commits = git_out(src, "rev-list", "--all").split()
        self.prefix: dict[str, str | None] = {}
        for c in (x.decode() for x in commits):
            for n in range(7, 41):
                k = c[:n]
                self.prefix[k] = None if k in self.prefix and self.prefix[k] != c else c
        self.old2new: dict[str, str] = {}
        self._paths: dict[bytes, bytes] = {}
        self.stats = {"blobs": 0, "blobs_changed": 0, "stubbed": 0,
                      "blob_replaced": 0, "paths_renamed": 0, "msgs_changed": 0,
                      "sha_refs": 0, "commits": 0, "tags": 0}

    def remap_shas(self, data: bytes) -> bytes:
        def sub(m: re.Match) -> bytes:
            orig = self.prefix.get(m.group(0).decode())
            if orig and orig in self.old2new:
                self.stats["sha_refs"] += 1
                return self.old2new[orig][:len(m.group(0))].encode()
            return m.group(0)
        return HEX.sub(sub, data)

    def text(self, data: bytes) -> bytes:
        if redact.is_binary(data):
            return data
        new = redact.encode(redact.rewrite_text(redact.decode(data), self.rules))
        return self.remap_shas(new)

    def path(self, p: bytes) -> bytes:
        if p not in self._paths:
            self._paths[p] = redact.encode(
                redact.rewrite_text(redact.decode(p), self.rules))
        return self._paths[p]

    def file(self, path: bytes, oid: str, data: bytes) -> bytes:
        """Expected bytes of one file of one tree (stub > blob > text)."""
        reason = redact.stub_reason(redact.decode(path), self.stub_rules)
        if reason is not None:
            return redact.stub_text(reason).encode()
        if oid in self.blob_map:
            return self.blob_map[oid]
        return self.text(data)


def collisions(src: str, refs: list[str], rw: Rewriter) -> list[str]:
    """Commits whose tree has two different paths mapping to one new path."""
    bad = []
    for c in git_out(src, "rev-list", *refs).decode().split():
        seen: dict[bytes, bytes] = {}
        for p in ls_tree(src, c):
            n = rw.path(p)
            if n in seen and seen[n] != p:
                bad.append(f"{c[:12]}: {redact.decode(n)}")
                break
            seen[n] = p
    return bad


# --------------------------------------------------------------------------
def run(args) -> int:
    dst = Path(args.dst)
    if dst.exists():
        print(f"{dst} already exists", file=sys.stderr)
        return 2
    rules = redact.load_rules()
    rw = Rewriter(rules, args.src)
    bad = collisions(args.src, args.ref, rw)
    if bad:
        print("refusing: path mapping would merge two different files in:",
              file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        return 1
    subprocess.run(["git", "init", "-q", "--bare", str(dst)], check=True)

    r_fd, w_fd = os.pipe()
    imp = subprocess.Popen(
        ["git", "-C", str(dst), "fast-import", "--quiet", "--force",
         f"--cat-blob-fd={w_fd}"],
        stdin=subprocess.PIPE, pass_fds=(w_fd,))
    os.close(w_fd)
    answers = os.fdopen(r_fd, "rb")
    exp = subprocess.Popen(
        ["git", "-C", args.src, "fast-export", "--show-original-ids",
         "--reencode=yes", "--signed-tags=strip", *args.ref],
        stdout=subprocess.PIPE)
    inp, out = exp.stdout, imp.stdin

    def read_data(header: bytes) -> bytes:
        data = inp.read(int(header.split()[1]))
        if inp.peek(1)[:1] == b"\n":          # optional LF after data:
            inp.read(1)                         # write_data emits its own
        return data

    def write_data(data: bytes) -> None:
        out.write(b"data %d\n" % len(data))
        out.write(data)
        out.write(b"\n")

    while True:
        line = inp.readline()
        if not line:
            break
        if line == b"blob\n":
            out.write(line)
            orig = None
            while True:
                l2 = inp.readline()
                if l2.startswith(b"original-oid "):
                    orig = l2.split()[1].decode()
                    out.write(l2)
                elif l2.startswith(b"data "):
                    data = read_data(l2)
                    rw.stats["blobs"] += 1
                    if orig in rw.blob_map:
                        new = rw.blob_map[orig]
                        rw.stats["blob_replaced"] += 1
                    else:
                        new = rw.text(data)
                    if new != data:
                        rw.stats["blobs_changed"] += 1
                    write_data(new)
                    break
                else:
                    out.write(l2)                     # mark
            continue
        if line.startswith(b"commit "):
            out.write(line)
            mark = orig = None
            changes: list[tuple[bytes, bytes, bytes]] = []
            while True:
                l2 = inp.readline()
                if l2.startswith(b"mark "):
                    mark = l2.split()[1]
                    out.write(l2)
                elif l2.startswith(b"original-oid "):
                    orig = l2.split()[1].decode()
                    out.write(l2)
                elif l2.startswith(b"data "):
                    msg = read_data(l2)
                    new = rw.text(msg)
                    if new != msg:
                        rw.stats["msgs_changed"] += 1
                    write_data(new)
                elif l2.startswith((b"M ", b"D ", b"C ", b"R ")) or l2 == b"deleteall\n":
                    changes.append(file_change(l2, rw))
                elif l2 == b"\n" or not l2:
                    out.write(settle(changes))
                    out.write(b"\n")
                    break
                else:
                    out.write(l2)                     # author/committer/from/merge
            rw.stats["commits"] += 1
            out.write(b"get-mark " + mark + b"\n")
            out.flush()
            new_sha = answers.readline().strip().decode()
            if orig:
                rw.old2new[orig] = new_sha
            continue
        if line.startswith(b"tag "):
            out.write(line)
            rw.stats["tags"] += 1
            while True:
                l2 = inp.readline()
                if l2.startswith(b"data "):
                    write_data(rw.text(read_data(l2)))
                    break
                out.write(l2)
            continue
        out.write(line)                               # reset/from/feature/done

    exp.wait()
    out.close()
    rc = imp.wait()
    answers.close()
    if exp.returncode or rc:
        print(f"fast-export rc={exp.returncode} fast-import rc={rc}", file=sys.stderr)
        return 1
    subprocess.run(["git", "-C", str(dst), "gc", "-q", "--prune=now"], check=True)
    with open(dst / "redaction-commit-map.tsv", "w") as f:
        for o, n in rw.old2new.items():
            f.write(f"{o}\t{n}\n")
    rw.stats["paths_renamed"] = sum(1 for k, v in rw._paths.items() if k != v)
    for k, v in rw.stats.items():
        print(f"{k}: {v}")
    return 0


def settle(changes: list[tuple[bytes, bytes, bytes]]) -> bytes:
    """Path mapping can turn `D old` + `M new` (a rename done by the redaction
    commit itself) into `D x` + `M x`, and `R old new` into `R x x`. Drop the
    deletes/renames that would now hit a path this same commit writes."""
    written = {p for op, p, _ in changes if op == b"M"}
    out = b""
    for op, p, ln in changes:
        if op == b"D" and p in written:
            continue
        if op == b"R" and p == b"":
            continue
        out += ln
    return out


def file_change(line: bytes, rw: Rewriter) -> tuple[bytes, bytes, bytes]:
    """Rewrite one filechange line; stubbed files become inline data.
    Returns (op, path key, rewritten line(s))."""
    if line == b"deleteall\n":
        return (b"deleteall", b"", line)
    body = line[:-1]
    op = body[:1]
    if op == b"M":
        _, mode, ref, raw = body.split(b" ", 3)
        p = unquote(raw)
        reason = redact.stub_reason(redact.decode(p), rw.stub_rules)
        newp = quote(rw.path(p))
        if reason is not None and ref != b"inline":
            rw.stats["stubbed"] += 1
            data = redact.stub_text(reason).encode()
            return (b"M", newp, b"M " + mode + b" inline " + newp + b"\n" +
                    b"data %d\n" % len(data) + data + b"\n")
        return (b"M", newp, b"M " + mode + b" " + ref + b" " + newp + b"\n")
    if op == b"D":
        p = quote(rw.path(unquote(body[2:])))
        return (b"D", p, b"D " + p + b"\n")
    rest = body[2:]                                  # C / R: two paths
    if rest.startswith(b'"'):
        end = rest.index(b'" ', 1) + 1
        a, b_ = rest[:end], rest[end + 1:]
    else:
        a, b_ = rest.split(b" ", 1)
    qa, qb = quote(rw.path(unquote(a))), quote(rw.path(unquote(b_)))
    if op == b"R" and qa == qb:
        return (b"R", b"", b"")                     # rename became a no-op
    return (op, qb, op + b" " + qa + b" " + qb + b"\n")


# --------------------------------------------------------------------------
def verify(args) -> int:
    rules = redact.load_rules()
    src, dst = args.src, args.dst
    fail = 0

    def ok(m):
        print(f"PASS  {m}")

    def bad(m):
        nonlocal fail
        fail = 1
        print(f"FAIL  {m}")

    m = dict(ln.split("\t") for ln in
             (Path(dst) / "redaction-commit-map.tsv").read_text().splitlines())
    rw = Rewriter(rules, src)
    rw.old2new = m

    src_commits = git_out(src, "rev-list", "--topo-order", *args.ref).decode().split()
    dst_commits = git_out(dst, "rev-list", "--all").decode().split()
    (ok if len(src_commits) == len(set(dst_commits)) == len(m)
     and all(c in m for c in src_commits) else bad)(
        f"提交数一致且全部有映射:src={len(src_commits)} dst={len(dst_commits)} map={len(m)}")

    # refs point at the mapped objects (tags: peeled commit + message)
    ref_bad = 0
    for r in args.ref:
        so = git_out(src, "rev-parse", f"{r}^{{commit}}").decode().strip()
        do = git_out(dst, "rev-parse", f"{r}^{{commit}}").decode().strip()
        if m.get(so) != do:
            ref_bad += 1
        if git_out(src, "cat-file", "-t", r).strip() == b"tag":
            sm = git_out(src, "cat-file", "tag", r).split(b"\n\n", 1)[1]
            dm = git_out(dst, "cat-file", "tag", r).split(b"\n\n", 1)[1]
            if rw.text(sm) != dm:
                ref_bad += 1
    dst_refs = git_out(dst, "for-each-ref", "--format=%(refname)").decode().split()
    (ok if ref_bad == 0 else bad)(
        f"{len(args.ref)} 个引用均指向映射后的对象(不符 {ref_bad});dst 引用 {len(dst_refs)} 个")

    # per commit: parents, author/committer, message, whole tree
    src_blobs: dict[str, bytes] = {}
    dst_blobs: dict[str, bytes] = {}
    expect_cache: dict[tuple[bytes, str], bytes] = {}
    meta_bad = tree_bad = files_checked = 0
    fmt = "%P%x00%an <%ae> %ad%x00%cn <%ce> %cd"
    for o in src_commits:
        n = m.get(o)
        if not n:
            continue
        po, ao, co = git_out(src, "log", "-1", "--date=raw", f"--format={fmt}", o
                             ).decode().rstrip("\n").split("\0")
        pn, an, cn = git_out(dst, "log", "-1", "--date=raw", f"--format={fmt}", n
                             ).decode().rstrip("\n").split("\0")
        msg_o = git_out(src, "cat-file", "commit", o).split(b"\n\n", 1)[1]
        msg_n = git_out(dst, "cat-file", "commit", n).split(b"\n\n", 1)[1]
        if ([m.get(p) for p in po.split()] != pn.split() or ao != an or co != cn
                or rw.text(msg_o) != msg_n):
            meta_bad += 1
            print(f"      提交元数据不符:{n[:12]}")
        st, dt = ls_tree(src, o), ls_tree(dst, n)
        src_blobs.update(cat(src, [oid for _, oid in st.values() if oid not in src_blobs]))
        dst_blobs.update(cat(dst, [oid for _, oid in dt.values() if oid not in dst_blobs]))
        expected = {}
        for p, (mode, oid) in st.items():
            key = (p, oid)
            if key not in expect_cache:
                expect_cache[key] = rw.file(p, oid, src_blobs[oid])
            expected[rw.path(p)] = (mode, expect_cache[key])
        got = {p: (mode, dst_blobs[oid]) for p, (mode, oid) in dt.items()}
        files_checked += len(expected)
        if expected != got:
            tree_bad += 1
            diff = sorted(set(expected) ^ set(got)) or sorted(
                p for p in expected if expected[p] != got.get(p))
            print(f"      树不符:{n[:12]}:{redact.decode(diff[0])} 等 {len(diff)} 处")
    (ok if meta_bad == 0 else bad)(f"逐提交父子、作者/提交者行、提交信息一致(不符 {meta_bad})")
    (ok if tree_bad == 0 else bad)(
        f"逐提交整棵树(路径/模式/内容)= 源树经同一变换:{len(src_commits)} 个提交、"
        f"{files_checked} 个文件版本,不符 {tree_bad} 个提交")

    # no detect hit anywhere in DST, no leftover old ids
    cwd = os.getcwd()
    os.chdir(dst)
    try:
        sc = redact.Scan(rules)
        redact.scan_commits(sc, ["--all"])
    finally:
        os.chdir(cwd)
    (ok if not sc.hits else bad)(
        f"dst 全历史(提交信息 + 全部 blob + 路径)无检测规则命中:"
        f"扫描 {sc.scanned} 项文本、{len(sc.binaries)} 个二进制,命中 {len(sc.hits)}")
    objs = git_out(dst, "cat-file", "--batch-all-objects", "--batch-check").decode().split("\n")
    texts = [o.split()[0] for o in objs if o and o.split()[1] in ("blob", "commit", "tag")]
    left = 0
    for data in cat(dst, texts).values():
        for tok in HEX.findall(data):
            orig = rw.prefix.get(tok.decode())
            if orig and orig in m and not m[orig].startswith(tok.decode()):
                left += 1
    (ok if left == 0 else bad)(f"dst 中残留的旧提交 id 引用:{left} 处")
    print("RESULT:", "PASS" if not fail else "FAIL")
    return fail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "verify"])
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--ref", action="append")
    a = ap.parse_args()
    a.ref = a.ref or ["master"]
    return run(a) if a.cmd == "run" else verify(a)


if __name__ == "__main__":
    sys.exit(main())
