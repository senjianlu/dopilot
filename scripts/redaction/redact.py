#!/usr/bin/env python3
"""dopilot public-repo redaction tool (stdlib only, Python >= 3.10).

Policy: docs/decisions/0024-public-repo-redaction.md. This file holds the
mechanism only; it contains NO business terms. Real terms live in a private,
never-committed rules file (default ~/.config/dopilot/redaction-rules.tsv,
override with DOPILOT_REDACTION_RULES; the value "none" consciously runs the
committed generic rules only).

Rules file: UTF-8, one rule per line, TAB-separated, '#' comments:

    lit      <literal>   <alias>    detect + rewrite. Case-insensitive, matched
                                    on word / camelCase boundaries, replacement
                                    keeps the match's case shape.
    re       <regex>     <repl>     detect + rewrite. Python regex as written,
                                    repl may use \\1 backrefs.
    rewrite  <regex>     <repl>     rewrite only, never reported. Use it only
                                    for cosmetic follow-ups; anything that is
                                    itself sensitive must be a `re` rule so
                                    the hooks can catch it.
    stub     <glob>      <reason>   whole-file stub (raw production data):
                                    content is replaced by a fixed notice.
    blob     <sha1>      <file>     history only: replace that blob's bytes
                                    with the given local file (e.g. a masked
                                    screenshot).

Rules apply sequentially in file order (each rule is its own pass), so put
longer literals before their prefixes. Aliases must not themselves match any
detect rule (``selftest`` checks this) -- that keeps ``apply`` idempotent.

Subcommands (exit 0 = clean / done, 1 = hits found, 2 = usage/config error):

    check --staged                  staged content + paths   (pre-commit)
    check --push [REMOTE]           pushed ref names, annotated tag messages
                                    and every commit REMOTE does not have
                                    yet (judged by refs/remotes/REMOTE/*),
                                    read from pre-push stdin  (pre-push)
    check --range A..B              commit messages + changed blobs + paths
    check --tree [--rev REV]        every tracked file: its content in the work
                                    tree, or in commit REV with --rev
    check --history                 every commit message, blob and path
                                    reachable from all refs
    check --files PATH...           the given files (content + path)

Every scan also enforces `stub` rules: a path that matches one may only
hold the exact stub notice -- raw production data is blocked even when it
contains no listed term. Merge commits are compared against every parent;
type changes (e.g. file <-> symlink) are scanned like any other change and
a symlink is scanned by its target, never followed.
    apply PATH... | apply -         rewrite files in place / stdin -> stdout
    apply-tree                      redact every tracked file of the current
                                    work tree: stub / blob / text rules, then
                                    `git mv` files whose path matches a rule
    stub-text REASON                print the stub notice for REASON
    selftest                        validate the rules file

Common options: --summary (counts per rule, never prints matched text --
use it for output that will be committed as evidence).
A line containing the marker ``redaction:allow`` is never reported.
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARKER = "redaction:allow"
HERE = Path(__file__).resolve().parent
GENERIC_RULES = HERE / "generic-rules.tsv"
ZERO = "0" * 40

STUB_TEMPLATE = (
    "# 本文件已移出公开仓库\n"
    "\n"
    "原内容是生产环境的原始数据({reason}),按 docs/decisions/0024 的脱敏规则\n"
    "不在公开仓库保留;引用本文件的结论以同任务的 plan / 调查报告正文为准。\n"
    "原件仅保存在维护者本机的私有备份中。\n"
)


def stub_text(reason: str) -> str:
    return STUB_TEMPLATE.format(reason=reason)


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------
@dataclass
class Rule:
    rid: str          # "private#12" / "generic#3"
    kind: str         # lit | re | rewrite | stub | blob
    pattern: str
    repl: str
    rx: re.Pattern | None = None

    @property
    def detects(self) -> bool:
        return self.kind in ("lit", "re")


def _ci_literal(lit: str) -> str:
    """Case-insensitive literal without a global (?i) so that the camelCase
    lookarounds below stay case-sensitive."""
    out = []
    for ch in lit:
        if ch.isalpha() and ch.lower() != ch.upper():
            out.append("[" + re.escape(ch.lower()) + re.escape(ch.upper()) + "]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


# start: not preceded by an alnum, OR a lower/digit->Upper camel boundary
_START = r"(?:(?<![A-Za-z0-9])|(?<=[a-z0-9])(?=[A-Z]))"
# end:   not followed by an alnum, OR the next char starts a new camel word
_END = r"(?:(?![A-Za-z0-9])|(?<=[a-z0-9])(?=[A-Z]))"


def compile_lit(lit: str) -> re.Pattern:
    return re.compile(_START + _ci_literal(lit) + _END)


def case_like(src: str, alias: str) -> str:
    letters = [c for c in src if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return alias.upper()
    if letters and all(c.islower() for c in letters):
        return alias.lower()
    if letters and letters[0].isupper() and all(c.islower() for c in letters[1:]):
        return alias[:1].upper() + alias[1:].lower()
    return alias


def config_error(msg: str) -> SystemExit:
    print(msg, file=sys.stderr)
    return SystemExit(2)


def parse_rules(path: Path, prefix: str) -> list[Rule]:
    rules: list[Rule] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise config_error(f"redaction: cannot read rules file {path}: {e}") from None
    for no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 3 or not parts[1]:
            raise config_error(f"{path}:{no}: expected 3 TAB-separated fields")
        kind, pat, repl = parts
        r = Rule(f"{prefix}#{no}", kind, pat, repl)
        if kind == "lit":
            r.rx = compile_lit(pat)
        elif kind in ("re", "rewrite"):
            try:
                r.rx = re.compile(pat)
            except re.error as e:
                raise config_error(f"{path}:{no}: bad regex: {e}") from None
        elif kind not in ("stub", "blob"):
            raise config_error(f"{path}:{no}: unknown kind {kind!r}")
        rules.append(r)
    return rules


def private_rules_path() -> Path | None:
    env = os.environ.get("DOPILOT_REDACTION_RULES")
    if env == "none":
        return None
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "dopilot" / "redaction-rules.tsv"


def load_rules() -> list[Rule]:
    if not GENERIC_RULES.is_file():
        raise config_error(
            f"redaction: generic rules file missing: {GENERIC_RULES} (fail-closed)")
    rules = parse_rules(GENERIC_RULES, "generic")
    p = private_rules_path()
    if p is None:
        print("redaction: DOPILOT_REDACTION_RULES=none -> generic rules only",
              file=sys.stderr)
        return rules
    if not p.exists():
        raise config_error(
            f"redaction: private rules file not found: {p}\n"
            "  put the maintainer's rules file there, point DOPILOT_REDACTION_RULES\n"
            "  at it, or set DOPILOT_REDACTION_RULES=none to run generic rules only\n"
            "  (see docs/decisions/0024).")
    return parse_rules(p, "private") + rules


# --------------------------------------------------------------------------
# rewrite / detect primitives
# --------------------------------------------------------------------------
def rewrite_text(text: str, rules: list[Rule]) -> str:
    for r in rules:
        if r.kind == "lit":
            text = r.rx.sub(lambda m, a=r.repl: case_like(m.group(0), a), text)
        elif r.kind in ("re", "rewrite"):
            text = r.rx.sub(r.repl, text)
    return text


def stub_rule(path: str, rules: list[Rule]) -> Rule | None:
    for r in rules:
        if r.kind == "stub" and fnmatch.fnmatchcase(path, r.pattern):
            return r
    return None


def stub_reason(path: str, rules: list[Rule]) -> str | None:
    r = stub_rule(path, rules)
    return r.repl if r else None


@dataclass
class Hit:
    where: str
    line: int
    rid: str
    text: str


def find_hits(where: str, text: str, rules: list[Rule]) -> list[Hit]:
    hits: list[Hit] = []
    for no, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line:
            continue
        for r in rules:
            if r.detects:
                for m in r.rx.finditer(line):
                    hits.append(Hit(where, no, r.rid, m.group(0)))
    return hits


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")


def encode(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogateescape")


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------
def git(*args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], input=input, check=True,
                          stdout=subprocess.PIPE).stdout


def cat_blobs(oids: list[str]) -> dict[str, bytes]:
    """Read many blobs through one `git cat-file --batch`."""
    out: dict[str, bytes] = {}
    if not oids:
        return out
    p = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE)
    data, _ = p.communicate("\n".join(oids).encode() + b"\n")
    pos = 0
    for oid in oids:
        nl = data.index(b"\n", pos)
        header = data[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] == b"missing":
            continue
        size = int(header[2])
        out[oid] = data[pos:pos + size]
        pos += size + 1
    return out


class Scan:
    def __init__(self, rules: list[Rule]):
        self.rules = rules
        self.hits: list[Hit] = []
        self.binaries: list[str] = []
        self.scanned = 0

    def text(self, where: str, text: str) -> None:
        self.scanned += 1
        self.hits += find_hits(where, text, self.rules)

    def blob(self, where: str, data: bytes) -> None:
        if is_binary(data):
            self.binaries.append(where)
            return
        self.text(where, decode(data))

    def path(self, where: str, path: str) -> None:
        self.hits += find_hits(f"{where} (path)", path, self.rules)

    def file(self, where: str, path: str, data: bytes) -> None:
        """One file version: path + content, with stub enforcement."""
        self.path(where, path)
        r = stub_rule(path, self.rules)
        if r is not None:
            self.scanned += 1
            if data != stub_text(r.repl).encode():
                self.hits.append(Hit(where, 0, r.rid,
                                     "<stub path holds content other than the stub notice>"))
            return
        self.blob(where, data)


def scan_staged(sc: Scan) -> None:
    out = git("diff", "--cached", "--name-status", "-z", "--no-renames",
              "--diff-filter=AMT")
    parts = out.split(b"\0")
    paths = [parts[i + 1].decode() for i in range(0, len(parts) - 1, 2)]
    entries = []
    for p in paths:
        line = git("ls-files", "-s", "--", p).split()
        entries.append((p, line[1].decode()))
    blobs = cat_blobs([oid for _, oid in entries])
    for p, oid in entries:
        sc.file(p, p, blobs.get(oid, b""))


def scan_tree(sc: Scan, rev: str | None) -> None:
    if rev:
        out = git("ls-tree", "-r", "-z", rev)
        entries = []
        for rec in out.split(b"\0"):
            if not rec:
                continue
            meta, path = rec.split(b"\t", 1)
            mode, typ, oid = meta.split()
            if typ == b"blob":
                entries.append((path.decode(), oid.decode()))
    else:                       # work tree: tracked paths, content as on disk
        top = Path(git("rev-parse", "--show-toplevel").decode().strip())
        scan_files(sc, [top / rec.decode() for rec in git("ls-files", "-z").split(b"\0")
                        if rec], top)
        return
    blobs = cat_blobs([oid for _, oid in entries])
    for p, oid in entries:
        sc.file(p, p, blobs.get(oid, b""))


def read_work_file(fp: Path) -> bytes | None:
    """A symlink is read as its target string (what git stores), never followed."""
    if fp.is_symlink():
        return os.fsencode(os.readlink(fp))
    return fp.read_bytes() if fp.is_file() else None


def scan_files(sc: Scan, files: list[Path], top: Path) -> None:
    for fp in files:
        data = read_work_file(fp)
        if data is None:
            continue
        # abspath, not resolve(): a symlink must keep its own path
        rel = Path(os.path.relpath(os.path.abspath(fp), top)).as_posix()
        sc.file(rel, rel, data)


def scan_commits(sc: Scan, revs: list[str]) -> None:
    """revs = rev-list arguments (e.g. ['A..B'] or ['--all'])."""
    commits = git("rev-list", *revs).decode().split()
    want: dict[tuple[str, str], str] = {}
    for c in commits:
        msg = git("log", "-1", "--format=%B", c).decode("utf-8", "surrogateescape")
        sc.text(f"commit {c[:12]} (message)", msg)
        # -m: a merge is compared against EVERY parent, so content that only
        # exists in the merge result is scanned too; T = type changes
        out = git("diff-tree", "-r", "-m", "-z", "--no-commit-id", "--root",
                  "--no-renames", "--diff-filter=AMT", c)
        parts = out.split(b"\0")
        i = 0
        while i < len(parts) - 1:
            meta = parts[i].decode()
            path = parts[i + 1].decode()
            i += 2
            if not meta.startswith(":"):
                continue
            new_oid = meta.split()[3]
            want.setdefault((new_oid, path), f"{path} @ {c[:12]}")
    blobs = cat_blobs(sorted({oid for oid, _ in want}))
    for (oid, path), where in want.items():
        sc.file(where, path, blobs.get(oid, b""))


def scan_push(sc: Scan, stdin_text: str, remote: str | None) -> None:
    """pre-push: ref names, annotated tag messages, and every commit that the
    remote does not have yet (messages, changed blobs, paths)."""
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        lref, lsha, rref, _ = parts
        if lsha == ZERO:
            continue        # deleting a remote ref publishes nothing: always allowed
        sc.path(f"ref {lref}", lref)
        if rref != lref:
            sc.path(f"ref {rref}", rref)
        sha = lsha
        typ = git("cat-file", "-t", sha).strip()
        while typ == b"tag":                    # annotated (possibly nested) tag
            body = git("cat-file", "tag", sha)
            header, _, msg = body.partition(b"\n\n")
            fields = dict(ln.split(b" ", 1) for ln in header.split(b"\n") if b" " in ln)
            sc.path(f"tag {lref} (name)", decode(fields.get(b"tag", b"")))
            sc.text(f"tag {lref} (message)", decode(msg))
            sha = fields[b"object"].decode()
            typ = git("cat-file", "-t", sha).strip()
        if typ == b"blob":                      # a tag may point at a blob ...
            sc.blob(f"tag {lref} -> blob", git("cat-file", "blob", sha))
        elif typ == b"tree":                    # ... or at a tree
            scan_tree(sc, sha)
    for rng in push_ranges(stdin_text, remote):
        scan_commits(sc, rng)


def push_ranges(stdin_text: str, remote: str | None = None) -> list[list[str]]:
    ranges = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _lref, lsha, _rref, rsha = parts
        if lsha == ZERO:
            continue                       # branch deletion: nothing to scan
        if subprocess.run(["git", "rev-parse", "-q", "--verify", f"{lsha}^{{commit}}"],
                          stdout=subprocess.DEVNULL).returncode != 0:
            continue                       # tag of a blob/tree: scanned in scan_push
        known = rsha != ZERO and subprocess.run(
            ["git", "cat-file", "-e", f"{rsha}^{{commit}}"],
            stderr=subprocess.DEVNULL).returncode == 0
        if known:
            ranges.append([f"{rsha}..{lsha}"])
        else:
            # new remote branch, or a remote tip this clone has never seen
            # (e.g. pushing rewritten history from a fresh repo). Only commits
            # known to be on THIS remote may be skipped; with no remote name
            # (pushing to a bare URL) nothing is skipped.
            if remote and remote_has_tracking_refs(remote):
                ranges.append([lsha, "--not", f"--remotes={remote}"])
            else:
                ranges.append([lsha])
    return ranges


def remote_has_tracking_refs(remote: str) -> bool:
    if "/" in remote or ":" in remote:          # a URL or path, not a remote name
        return False
    return bool(git("for-each-ref", "--format=%(refname)", f"refs/remotes/{remote}/"))


def report(sc: Scan, summary: bool, allow_binary: bool) -> int:
    by_rule: dict[str, int] = {}
    for h in sc.hits:
        by_rule[h.rid] = by_rule.get(h.rid, 0) + 1
        if not summary:
            print(f"HIT  {h.where}:{h.line}  [{h.rid}]  {h.text}")
    if sc.binaries:
        tag = "NOTE" if allow_binary else "BINARY"
        for b in sc.binaries:
            if not summary:
                print(f"{tag}  {b}  (binary content cannot be scanned)")
    print(f"redaction: scanned {sc.scanned} text item(s), "
          f"{len(sc.binaries)} binary, {len(sc.hits)} hit(s)")
    for rid in sorted(by_rule):
        print(f"  {rid}: {by_rule[rid]}")
    blocked = bool(sc.hits) or (bool(sc.binaries) and not allow_binary)
    if sc.binaries and not allow_binary:
        print("redaction: binary files must be reviewed by a human (screenshots"
              " leak business data); re-run with DOPILOT_REDACTION_ALLOW_BINARY=1"
              " after checking them")
    return 1 if blocked else 0


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_check(argv: list[str]) -> int:
    summary = "--summary" in argv
    argv = [a for a in argv if a != "--summary"]
    rules = load_rules()
    sc = Scan(rules)
    allow_binary = os.environ.get("DOPILOT_REDACTION_ALLOW_BINARY") == "1"
    if argv[:1] == ["--staged"]:
        scan_staged(sc)
    elif argv[:1] == ["--push"] and len(argv) <= 2:
        scan_push(sc, sys.stdin.read(), argv[1] if len(argv) == 2 else None)
    elif argv[:1] == ["--files"] and len(argv) >= 2:
        top = Path(git("rev-parse", "--show-toplevel").decode().strip())
        scan_files(sc, [Path(a).absolute() for a in argv[1:]], top)
    elif argv[:1] == ["--range"] and len(argv) == 2:
        scan_commits(sc, [argv[1]])
    elif argv[:1] == ["--tree"]:
        rev = argv[2] if argv[1:2] == ["--rev"] and len(argv) == 3 else None
        scan_tree(sc, rev)
        allow_binary = True     # whole-tree audit: binaries are listed, not fatal
    elif argv[:1] == ["--history"]:
        scan_commits(sc, ["--all"])
        allow_binary = True
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return report(sc, summary, allow_binary)


def cmd_apply(argv: list[str]) -> int:
    rules = load_rules()
    if argv == ["-"]:
        data = sys.stdin.buffer.read()
        sys.stdout.buffer.write(encode(rewrite_text(decode(data), rules)))
        return 0
    if not argv:
        print("usage: redact.py apply PATH... | apply -", file=sys.stderr)
        return 2
    changed = 0
    for p in argv:
        fp = Path(p)
        data = fp.read_bytes()
        if is_binary(data):
            print(f"skip binary {p}", file=sys.stderr)
            continue
        new = encode(rewrite_text(decode(data), rules))
        if new != data:
            fp.write_bytes(new)
            changed += 1
    print(f"redaction: rewrote {changed} of {len(argv)} file(s)", file=sys.stderr)
    return 0


def cmd_apply_tree() -> int:
    rules = load_rules()
    stubs = [r for r in rules if r.kind == "stub"]
    blob_map = {r.pattern: Path(r.repl).expanduser().read_bytes()
                for r in rules if r.kind == "blob"}
    out = git("ls-files", "-s", "-z")
    entries = []
    for rec in out.split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            entries.append((path.decode(), meta.split()[1].decode()))
    n = {"stub": 0, "blob": 0, "text": 0, "renamed": 0}
    for path, oid in entries:
        fp = Path(path)
        if fp.is_symlink():            # never follow: rewrite the target string
            target = os.readlink(fp)
            new_target = rewrite_text(target, rules)
            if new_target != target:
                fp.unlink()
                os.symlink(new_target, fp)
                n["text"] += 1
        elif fp.is_file():
            redact_file(fp, path, oid, stubs, blob_map, rules, n)
        newpath = rewrite_text(path, rules)
        if newpath != path:
            Path(newpath).parent.mkdir(parents=True, exist_ok=True)
            git("mv", "--", path, newpath)
            n["renamed"] += 1
    print("redaction: stubbed {stub}, replaced {blob} binary, rewrote {text} text, "
          "renamed {renamed}".format(**n))
    return 0


def redact_file(fp: Path, path: str, oid: str, stubs, blob_map, rules, n) -> None:
    """Redact one regular file in place (stub > blob > text)."""
    data = fp.read_bytes()
    reason = stub_reason(path, stubs)
    if reason is not None:
        new, key = stub_text(reason).encode(), "stub"
    elif oid in blob_map:
        new, key = blob_map[oid], "blob"
    elif is_binary(data):
        new, key = data, "text"
    else:
        new, key = encode(rewrite_text(decode(data), rules)), "text"
    if new != data:
        fp.write_bytes(new)
        n[key] += 1


def cmd_selftest() -> int:
    rules = load_rules()
    bad = 0
    for r in rules:
        if r.kind in ("lit", "re", "rewrite"):
            for d in rules:
                if d.detects and d.rx.search(r.repl):
                    print(f"alias of {r.rid} is itself matched by {d.rid}")
                    bad += 1
        if r.kind == "blob" and not Path(r.repl).expanduser().is_file():
            print(f"{r.rid}: replacement file missing")
            bad += 1
    print(f"redaction: {len(rules)} rule(s), {bad} problem(s)")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "check":
        return cmd_check(rest)
    if cmd == "apply":
        return cmd_apply(rest)
    if cmd == "apply-tree" and not rest:
        return cmd_apply_tree()
    if cmd == "stub-text" and len(rest) == 1:
        sys.stdout.write(stub_text(rest[0]))
        return 0
    if cmd == "selftest":
        return cmd_selftest()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
