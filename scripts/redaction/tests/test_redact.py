"""Tests for scripts/redaction (docs/decisions/0024).

Every term here is synthetic ("acmemart", "acmemart-spider", ...). The private
rules file is never read: DOPILOT_REDACTION_RULES points at a file built by
each test, so the suite is deterministic on any machine and safe to publish.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent.parent
REDACT = TOOLS / "redact.py"
REWRITE = TOOLS / "rewrite_history.py"


def _load_redact():
    spec = importlib.util.spec_from_file_location("redact_under_test", REDACT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod             # dataclasses resolve via sys.modules
    spec.loader.exec_module(mod)
    return mod


redact = _load_redact()

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00acmemart-pixels"
MASKED_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00masked-pixels"


def write_rules(path: Path, extra: str = "") -> Path:
    t = "\t"
    lines = [
        "# synthetic private rules",
        f"lit{t}acmemart-spider{t}crawler-a",
        f"lit{t}acmemart{t}site-q",
        f"lit{t}c3d{t}otc",
        f"re{t}\\bbetahost-(\\d+)\\b{t}agent-host-\\1",
        f"re{t}(?i)(\\bsite-[a-z]{{1,2}}(?:[ _-][a-z0-9]+)?[ _-])4242\\b{t}\\g<1>g1",
        f"rewrite{t}\\bcosmeticword\\b{t}tidyword",
        f"stub{t}raw/*.txt{t}synthetic raw dump",
    ]
    path.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
    return path


@pytest.fixture()
def rules(tmp_path, monkeypatch):
    p = write_rules(tmp_path / "rules.tsv")
    monkeypatch.setenv("DOPILOT_REDACTION_RULES", str(p))
    return redact.load_rules()


def run_tool(*args, env=None, cwd=None, input=None):
    return subprocess.run([sys.executable, str(REDACT), *args], cwd=cwd, env=env,
                          input=input, capture_output=True, text=True)


# ---------------------------------------------------------------- semantics
def test_lit_respects_word_boundaries(rules):
    assert redact.rewrite_text("acmemart quotes", rules) == "site-q quotes"
    assert redact.rewrite_text("acmemartx xacmemart", rules) == "acmemartx xacmemart"
    assert redact.rewrite_text("path/acmemart-log.txt", rules) == "path/site-q-log.txt"


def test_lit_matches_camel_case_segments(rules):
    assert redact.rewrite_text("websiteAcmemartPipeline", rules) == "websiteSite-qPipeline"


def test_lit_keeps_case_shape(rules):
    assert redact.rewrite_text("ACMEMART", rules) == "SITE-Q"
    assert redact.rewrite_text("Acmemart", rules) == "Site-q"
    assert redact.rewrite_text("acmemart", rules) == "site-q"


def test_lit_never_touches_hex_strings(rules):
    text = "commit a7c3d2b and c3d094e7 but QUOTE c3d"
    assert redact.rewrite_text(text, rules) == "commit a7c3d2b and c3d094e7 but QUOTE otc"


def test_rules_apply_in_file_order(rules):
    text = "acmemart-spider | ACMEMART 4242"
    assert redact.rewrite_text(text, rules) == "crawler-a | SITE-Q g1"


def test_regex_rule_with_backref(rules):
    assert redact.rewrite_text("betahost-02 up", rules) == "agent-host-02 up"


def test_rewrite_rules_are_not_detections(rules):
    assert redact.rewrite_text("a cosmeticword b", rules) == "a tidyword b"
    assert redact.find_hits("x", "a cosmeticword b", rules) == []


def test_alias_followed_by_a_real_appid_is_still_detected(rules):
    hits = redact.find_hits("x", "SITE-Q 4242 and SITE-Q verify 4242", rules)
    assert len(hits) == 2                          # alias + real appid: blocked
    assert redact.find_hits("x", "SITE-Q g1", rules) == []
    once = redact.rewrite_text("ACMEMART 4242 / SITE-Q verify 4242", rules)
    assert once == "SITE-Q g1 / SITE-Q verify g1"
    assert redact.rewrite_text(once, rules) == once    # idempotent


def test_allow_marker_suppresses_hits(rules):
    assert redact.find_hits("x", "acmemart  # redaction:allow", rules) == []


def test_stub_glob(rules):
    assert redact.stub_reason("raw/dump.txt", rules) == "synthetic raw dump"
    assert redact.stub_reason("raw/sub/dump.txt", rules) == "synthetic raw dump"
    assert redact.stub_reason("notes/dump.txt", rules) is None
    assert "synthetic raw dump" in redact.stub_text("synthetic raw dump")


def test_binary_detection():
    assert redact.is_binary(PNG_BYTES)
    assert not redact.is_binary("中文 text".encode())


def test_apply_from_stdin(tmp_path):
    env = dict(os.environ, DOPILOT_REDACTION_RULES=str(write_rules(tmp_path / "r.tsv")))
    r = run_tool("apply", "-", env=env, input="see ACMEMART 4242\n")
    assert r.returncode == 0 and r.stdout == "see SITE-Q g1\n"


def test_selftest_flags_alias_that_is_itself_detected(tmp_path):
    p = write_rules(tmp_path / "r.tsv", "lit\tzeta\tacmemart-two\n")
    env = dict(os.environ, DOPILOT_REDACTION_RULES=str(p))
    r = run_tool("selftest", env=env)
    assert r.returncode == 1 and "is itself matched" in r.stdout
    ok = run_tool("selftest", env=dict(os.environ, DOPILOT_REDACTION_RULES=str(
        write_rules(tmp_path / "ok.tsv"))))
    assert ok.returncode == 0


def test_missing_private_rules_fails_closed(tmp_path):
    env = dict(os.environ, DOPILOT_REDACTION_RULES=str(tmp_path / "absent.tsv"))
    r = run_tool("check", "--tree", env=env, cwd=REPO)
    assert r.returncode == 2
    assert "private rules file not found" in r.stderr


def test_none_runs_generic_rules_only(tmp_path):
    env = dict(os.environ, DOPILOT_REDACTION_RULES="none")
    private_ip = "10." + "20.30.40"           # built at runtime: keep the file clean
    r = run_tool("apply", "-", env=env, input=f"acmemart at {private_ip}\n")
    assert r.returncode == 0
    assert r.stdout == "acmemart at 192.0.2.1\n"


# ---------------------------------------------------------------- git helpers
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args, env=None, check=True):
    e = dict(os.environ, **GIT_ENV, **(env or {}))
    e["HOME"] = str(repo.parent)            # no user-level config leaks in
    return subprocess.run(["git", "-C", str(repo), *args], env=e, check=check,
                          capture_output=True, text=True)


def make_hooked_repo(tmp_path, rules_file):
    """A throwaway repo that carries this repo's tools and hooks."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    shutil.copytree(TOOLS, repo / "scripts" / "redaction",
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copytree(REPO / ".githooks", repo / ".githooks")
    git(repo, "config", "core.hooksPath", ".githooks")
    env = {"DOPILOT_REDACTION_RULES": str(rules_file)}
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-q", "-m", "chore: add tooling", env=env)
    return repo, env


# ---------------------------------------------------------------- hooks
def test_hook_pre_commit_blocks_sensitive_staged_content(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "notes.md").write_text("we read ACMEMART quotes\n")
    git(repo, "add", "notes.md", env=env)
    r = git(repo, "commit", "-m", "docs: add notes", env=env, check=False)
    assert r.returncode != 0
    assert "HIT  notes.md:1" in r.stdout + r.stderr


def test_hook_pre_commit_blocks_sensitive_path(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "acmemart-log.txt").write_text("clean\n")
    git(repo, "add", "-A", env=env)
    r = git(repo, "commit", "-m", "docs: add log", env=env, check=False)
    assert r.returncode != 0 and "(path)" in r.stdout + r.stderr


def test_hook_pre_commit_allows_clean_commit_and_commit_msg_still_runs(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "notes.md").write_text("we read SITE-Q quotes\n")
    git(repo, "add", "notes.md", env=env)
    bad_header = git(repo, "commit", "-m", "added notes", env=env, check=False)
    assert bad_header.returncode != 0          # commit-msg hook still enforced
    ok = git(repo, "commit", "-m", "docs: add notes", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_commit_fails_closed_without_rules_file(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "notes.md").write_text("clean\n")
    missing = {"DOPILOT_REDACTION_RULES": str(tmp_path / "absent.tsv")}
    git(repo, "add", "notes.md", env=missing)
    r = git(repo, "commit", "-m", "docs: add notes", env=missing, check=False)
    assert r.returncode != 0 and "private rules file not found" in r.stderr


def test_hook_binary_is_blocked_until_a_human_allows_it(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "shot.png").write_bytes(PNG_BYTES)
    git(repo, "add", "shot.png", env=env)
    r = git(repo, "commit", "-m", "docs: add shot", env=env, check=False)
    assert r.returncode != 0 and "BINARY" in r.stdout + r.stderr   # git sends hook stdout to stderr
    ok = git(repo, "commit", "-m", "docs: add shot",
             env={**env, "DOPILOT_REDACTION_ALLOW_BINARY": "1"}, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_blocks_sensitive_commit_message(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    first = git(repo, "push", "-q", "origin", "master", env=env, check=False)
    assert first.returncode == 0, first.stdout + first.stderr
    (repo / "a.txt").write_text("clean\n")
    git(repo, "add", "a.txt", env=env)
    git(repo, "commit", "-q", "-m", "fix: handle ACMEMART timeout", env=env)
    r = git(repo, "push", "origin", "master", env=env, check=False)
    assert r.returncode != 0 and "(message)" in r.stdout + r.stderr
    git(repo, "commit", "-q", "--amend", "-m", "fix: handle upstream timeout", env=env)
    ok = git(repo, "push", "-q", "origin", "master", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


# ---------------------------------------------------------------- history rewrite
def test_rewrite_history_end_to_end(tmp_path):
    masked = tmp_path / "masked.png"
    masked.write_bytes(MASKED_BYTES)
    rules_file = write_rules(tmp_path / "r.tsv")
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "master")
    (src / "README.md").write_text("hello\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "chore: init")
    (src / "notes").mkdir()
    (src / "notes" / "acmemart-log.txt").write_text("acmemart-spider | ACMEMART 4242\n")
    (src / "raw").mkdir()
    (src / "raw" / "dump.txt").write_text("raw betahost-01 acmemart dump\n")
    (src / "shot.png").write_bytes(PNG_BYTES)
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "docs: add ACMEMART evidence")
    c2 = git(src, "rev-parse", "HEAD").stdout.strip()
    blob = git(src, "rev-parse", "HEAD:shot.png").stdout.strip()
    rules_file.write_text(rules_file.read_text() + f"blob\t{blob}\t{masked}\n")
    (src / "followup.md").write_text(f"see {c2[:7]} and {c2[:12]}\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", f"docs: follow up on {c2[:7]}")
    # the redaction commit itself: rename + rewrite, as apply-tree would
    git(src, "mv", "notes/acmemart-log.txt", "notes/site-q-log.txt")
    (src / "notes" / "site-q-log.txt").write_text("crawler-a | SITE-Q g1\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "chore: redact")

    env = dict(os.environ, DOPILOT_REDACTION_RULES=str(rules_file))
    dst = tmp_path / "dst.git"
    run = subprocess.run([sys.executable, str(REWRITE), "run", "--src", str(src),
                          "--dst", str(dst)], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    ver = subprocess.run([sys.executable, str(REWRITE), "verify", "--src", str(src),
                          "--dst", str(dst)], env=env, capture_output=True, text=True)
    assert ver.returncode == 0 and "RESULT: PASS" in ver.stdout, ver.stdout + ver.stderr

    mapping = dict(line.split("\t") for line in
                   (dst / "redaction-commit-map.tsv").read_text().splitlines())
    new_c2 = mapping[c2]

    def show(spec):
        return subprocess.run(["git", "-C", str(dst), "show", spec], check=True,
                              capture_output=True).stdout

    assert show("master:notes/site-q-log.txt") == b"crawler-a | SITE-Q g1\n"
    assert show("master:followup.md") == f"see {new_c2[:7]} and {new_c2[:12]}\n".encode()
    assert show(f"{new_c2}:raw/dump.txt") == redact.stub_text("synthetic raw dump").encode()
    assert show(f"{new_c2}:shot.png") == MASKED_BYTES
    assert show(f"{new_c2}:notes/site-q-log.txt") == b"crawler-a | SITE-Q g1\n"
    log = subprocess.run(["git", "-C", str(dst), "log", "--format=%s", "master"],
                         check=True, capture_output=True, text=True).stdout
    assert "docs: add SITE-Q evidence" in log
    assert f"docs: follow up on {new_c2[:7]}" in log
    assert c2[:7] not in log


# ---------------------------------------------------------------- more hook edges
def test_hook_pre_commit_scans_the_index_not_the_work_tree(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "notes.md").write_text("ACMEMART\n")
    git(repo, "add", "notes.md", env=env)
    (repo / "notes.md").write_text("clean now\n")       # work tree cleaned, index not
    r = git(repo, "commit", "-m", "docs: add notes", env=env, check=False)
    assert r.returncode != 0 and "HIT  notes.md:1" in r.stdout + r.stderr


@pytest.mark.parametrize("content, expect", [
    ("lit\tacmemart\n", "expected 3 TAB-separated fields"),
    ("re\t([unclosed\tx\n", "bad regex"),
    ("bogus\tx\ty\n", "unknown kind"),
])
def test_hook_pre_commit_fails_closed_on_malformed_rules(tmp_path, content, expect):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    broken = tmp_path / "broken.tsv"
    broken.write_text(content)
    (repo / "a.txt").write_text("clean\n")
    benv = {"DOPILOT_REDACTION_RULES": str(broken)}
    git(repo, "add", "a.txt", env=benv)
    r = git(repo, "commit", "-m", "docs: a", env=benv, check=False)
    assert r.returncode != 0 and expect in r.stderr


def test_hook_pre_commit_fails_closed_on_unreadable_rules(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    locked = write_rules(tmp_path / "locked.tsv")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("running with privileges that bypass file modes")
        (repo / "a.txt").write_text("clean\n")
        lenv = {"DOPILOT_REDACTION_RULES": str(locked)}
        git(repo, "add", "a.txt", env=lenv)
        r = git(repo, "commit", "-m", "docs: a", env=lenv, check=False)
        assert r.returncode != 0 and "cannot read rules file" in r.stderr
    finally:
        locked.chmod(0o600)


def test_hook_pre_commit_fails_closed_without_python3(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "a.txt").write_text("clean\n")
    git(repo, "add", "a.txt", env=env)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "git").symlink_to(shutil.which("git"))      # git only, no python3
    r = subprocess.run(["git", "-C", str(repo), "commit", "-m", "docs: a"],
                       env={**os.environ, **GIT_ENV, **env, "PATH": str(bindir),
                            "HOME": str(tmp_path)},
                       capture_output=True, text=True)
    assert r.returncode != 0 and "需要 python3" in r.stderr


def _remote(repo, tmp_path, env):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    r = git(repo, "push", "-q", "origin", "master", env=env, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    return remote


@pytest.mark.parametrize("make_commit", ["content", "path", "earlier-then-cleaned"])
def test_hook_pre_push_scans_contents_paths_and_every_pushed_commit(tmp_path, make_commit):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    allow = {**env, "DOPILOT_REDACTION_RULES": "none"}   # let the commits in locally
    if make_commit == "content":
        (repo / "a.txt").write_text("ACMEMART\n")
    elif make_commit == "path":
        (repo / "acmemart.txt").write_text("clean\n")
    else:
        (repo / "a.txt").write_text("ACMEMART\n")
        git(repo, "add", "-A", env=allow)
        git(repo, "commit", "-q", "-m", "docs: a", env=allow)
        (repo / "a.txt").write_text("clean\n")
    git(repo, "add", "-A", env=allow)
    git(repo, "commit", "-q", "-m", "docs: b", env=allow)
    r = git(repo, "push", "origin", "master", env=env, check=False)
    assert r.returncode != 0 and "HIT" in r.stdout + r.stderr


def test_hook_pre_push_unknown_remote_tip_scans_whole_new_history(tmp_path):
    rules_file = write_rules(tmp_path / "r.tsv")
    repo, env = make_hooked_repo(tmp_path, rules_file)
    remote = _remote(repo, tmp_path, env)
    # a second, unrelated history (like rewritten history) that never fetched the remote
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other, _ = make_hooked_repo(other_dir, rules_file)
    allow = {**env, "DOPILOT_REDACTION_RULES": "none"}
    (other / "a.txt").write_text("ACMEMART\n")
    git(other, "add", "-A", env=allow)
    git(other, "commit", "-q", "-m", "docs: a", env=allow)
    (other / "a.txt").write_text("clean\n")
    git(other, "add", "-A", env=allow)
    git(other, "commit", "-q", "-m", "docs: b", env=allow)
    git(other, "remote", "add", "origin", str(remote))
    r = git(other, "push", "--force", "origin", "master", env=env, check=False)
    assert r.returncode != 0 and "HIT" in r.stdout + r.stderr
    git(other, "reset", "-q", "--hard", "HEAD~2", env=env)
    ok = git(other, "push", "-q", "--force", "origin", "master", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_scans_annotated_tag_message_on_an_already_pushed_commit(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)                       # the commit is already remote
    git(repo, "tag", "-a", "v1", "-m", "release for ACMEMART", env=env)
    r = git(repo, "push", "origin", "v1", env=env, check=False)
    assert r.returncode != 0 and "tag refs/tags/v1 (message)" in r.stdout + r.stderr
    git(repo, "tag", "-d", "v1", env=env)
    git(repo, "tag", "-a", "v1", "-m", "release 1", env=env)
    ok = git(repo, "push", "-q", "origin", "v1", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_follows_nested_tags(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)                       # the commit is already remote
    git(repo, "tag", "-a", "inner", "-m", "inner note on ACMEMART", env=env)
    git(repo, "tag", "-a", "outer", "-m", "clean outer", "inner", env=env)  # tag of a tag
    assert git(repo, "cat-file", "-t", "outer^{}").stdout.strip() == "commit"
    r = git(repo, "push", "origin", "outer", env=env, check=False)
    assert r.returncode != 0 and "tag refs/tags/outer (message)" in r.stdout + r.stderr
    git(repo, "tag", "-d", "outer", "inner", env=env)
    git(repo, "tag", "-a", "inner", "-m", "inner note", env=env)
    git(repo, "tag", "-a", "outer", "-m", "clean outer", "inner", env=env)
    ok = git(repo, "push", "-q", "origin", "outer", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_scans_ref_names(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    git(repo, "branch", "fix-acmemart", env=env)
    r = git(repo, "push", "origin", "fix-acmemart", env=env, check=False)
    assert r.returncode != 0 and "ref refs/heads/fix-acmemart" in r.stdout + r.stderr
    git(repo, "branch", "-m", "fix-acmemart", "fix-upstream", env=env)
    ok = git(repo, "push", "-q", "origin", "fix-upstream", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_binary_blocked_until_allowed(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    (repo / "shot.png").write_bytes(PNG_BYTES)
    git(repo, "add", "shot.png", env=env)
    git(repo, "commit", "-q", "-m", "docs: shot",
        env={**env, "DOPILOT_REDACTION_ALLOW_BINARY": "1"})
    r = git(repo, "push", "origin", "master", env=env, check=False)
    assert r.returncode != 0 and "BINARY" in r.stdout + r.stderr
    ok = git(repo, "push", "-q", "origin", "master",
             env={**env, "DOPILOT_REDACTION_ALLOW_BINARY": "1"}, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


# ---------------------------------------------------------------- rewrite edges
def _rewrite(args, rules_file):
    env = dict(os.environ, DOPILOT_REDACTION_RULES=str(rules_file))
    return subprocess.run([sys.executable, str(REWRITE), *args], env=env,
                          capture_output=True, text=True)


def test_rewrite_refuses_real_path_collision(tmp_path):
    rules_file = write_rules(tmp_path / "r.tsv")
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "master")
    (src / "acmemart.txt").write_text("one\n")
    (src / "site-q.txt").write_text("two\n")             # different file, same new name
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "chore: init")
    dst = tmp_path / "dst.git"
    r = _rewrite(["run", "--src", str(src), "--dst", str(dst)], rules_file)
    assert r.returncode == 1 and "refusing" in r.stderr
    assert not dst.exists()


def test_rewrite_handles_extra_branches_and_annotated_tags(tmp_path):
    rules_file = write_rules(tmp_path / "r.tsv")
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "master")
    (src / "a.txt").write_text("acmemart\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "chore: init")
    git(src, "tag", "-a", "v1", "-m", "release for ACMEMART")
    git(src, "checkout", "-q", "-b", "feat")
    (src / "b.txt").write_text("ACMEMART 4242\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "feat: ACMEMART")
    git(src, "checkout", "-q", "master")

    every = tmp_path / "every.git"
    refs = ["--ref", "master", "--ref", "feat", "--ref", "v1"]
    assert _rewrite(["run", "--src", str(src), "--dst", str(every), *refs],
                    rules_file).returncode == 0
    v = _rewrite(["verify", "--src", str(src), "--dst", str(every), *refs], rules_file)
    assert v.returncode == 0 and "RESULT: PASS" in v.stdout, v.stdout
    names = subprocess.run(["git", "-C", str(every), "for-each-ref", "--format=%(refname)"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert sorted(names) == ["refs/heads/feat", "refs/heads/master", "refs/tags/v1"]
    tag = subprocess.run(["git", "-C", str(every), "cat-file", "tag", "v1"],
                         capture_output=True, text=True, check=True).stdout
    assert "release for SITE-Q" in tag and "ACMEMART" not in tag
    feat_b = subprocess.run(["git", "-C", str(every), "show", "feat:b.txt"],
                            capture_output=True, text=True, check=True).stdout
    assert feat_b == "SITE-Q g1\n"

    only = tmp_path / "only.git"
    assert _rewrite(["run", "--src", str(src), "--dst", str(only)], rules_file).returncode == 0
    names = subprocess.run(["git", "-C", str(only), "for-each-ref", "--format=%(refname)"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert names == ["refs/heads/master"]                # out-of-scope refs not exported


def test_verify_catches_a_corrupted_intermediate_commit_with_a_healthy_tip(tmp_path):
    rules_file = write_rules(tmp_path / "r.tsv")
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "master")
    (src / "keep.txt").write_text("keep\n")
    (src / "tmp").mkdir()
    (src / "tmp" / "scratch.txt").write_text("intermediate acmemart\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "chore: init")
    git(src, "rm", "-q", "tmp/scratch.txt")
    git(src, "commit", "-q", "-m", "chore: drop scratch")
    good = tmp_path / "good.git"
    assert _rewrite(["run", "--src", str(src), "--dst", str(good)], rules_file).returncode == 0
    # a dst whose FIRST commit differs (scratch.txt stubbed) but whose tip is identical
    skewed_rules = write_rules(tmp_path / "skewed.tsv", "stub\ttmp/*.txt\tskew\n")
    bad = tmp_path / "bad.git"
    assert _rewrite(["run", "--src", str(src), "--dst", str(bad)], skewed_rules).returncode == 0
    tip = [subprocess.run(["git", "-C", str(d), "rev-parse", "master^{tree}"],
                          capture_output=True, text=True, check=True).stdout for d in (good, bad)]
    assert tip[0] == tip[1]                              # a tip-only check would pass
    v = _rewrite(["verify", "--src", str(src), "--dst", str(bad)], rules_file)
    assert v.returncode != 0 and "树不符" in v.stdout and "RESULT: FAIL" in v.stdout


# ---------------------------------------------------------------- review round 1 edges
def test_hook_fails_closed_when_generic_rules_file_is_missing(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "scripts" / "redaction" / "generic-rules.tsv").unlink()
    (repo / "a.txt").write_text("clean\n")
    for e in (env, {"DOPILOT_REDACTION_RULES": "none"}):
        git(repo, "add", "-A", env=e)
        r = git(repo, "commit", "-m", "docs: a", env=e, check=False)
        assert r.returncode != 0 and "generic rules file missing" in r.stderr


def test_hook_stub_paths_only_accept_the_stub_notice(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "raw").mkdir()
    (repo / "raw" / "dump.txt").write_text("12:00 rows=8107 ok\n")   # no listed term
    git(repo, "add", "-A", env=env)
    r = git(repo, "commit", "-m", "docs: raw", env=env, check=False)
    assert r.returncode != 0 and "stub path holds content" in r.stdout + r.stderr
    files = run_tool("check", "--files", "raw/dump.txt", env=dict(os.environ, **env), cwd=repo)
    assert files.returncode == 1 and "stub path holds content" in files.stdout
    (repo / "raw" / "dump.txt").write_text(redact.stub_text("synthetic raw dump"))
    git(repo, "add", "-A", env=env)
    ok = git(repo, "commit", "-m", "docs: raw", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_check_files_scans_untracked_files(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    (repo / "new.md").write_text("ACMEMART\n")
    r = run_tool("check", "--files", "new.md", env=dict(os.environ, **env), cwd=repo)
    assert r.returncode == 1 and "HIT  new.md:1" in r.stdout


def test_hook_pre_push_scans_content_that_only_exists_in_a_merge(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    allow = {**env, "DOPILOT_REDACTION_RULES": "none"}
    git(repo, "checkout", "-q", "-b", "side", env=env)
    (repo / "b.txt").write_text("side\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-q", "-m", "docs: side", env=env)
    git(repo, "checkout", "-q", "master", env=env)
    (repo / "c.txt").write_text("main\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-q", "-m", "docs: main", env=env)
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side", env=allow)
    (repo / "merged.txt").write_text("ACMEMART\n")        # only in the merge result
    git(repo, "add", "-A", env=allow)
    git(repo, "commit", "-q", "-m", "chore: merge side", env=allow)
    r = git(repo, "push", "origin", "master", env=env, check=False)
    assert r.returncode != 0 and "merged.txt" in r.stdout + r.stderr


def test_hook_pre_push_does_not_trust_other_remotes(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    allow = {**env, "DOPILOT_REDACTION_RULES": "none"}
    private = tmp_path / "private.git"
    public = tmp_path / "public.git"
    for r in (private, public):
        subprocess.run(["git", "init", "-q", "--bare", str(r)], check=True)
    git(repo, "remote", "add", "private", str(private))
    git(repo, "remote", "add", "public", str(public))
    (repo / "a.txt").write_text("ACMEMART\n")
    git(repo, "add", "-A", env=allow)
    git(repo, "commit", "-q", "-m", "docs: internal", env=allow)
    git(repo, "push", "-q", "private", "master", env=allow)        # now on private/master
    r = git(repo, "push", "public", "master", env=env, check=False)
    assert r.returncode != 0 and "HIT" in r.stdout + r.stderr


def test_hooks_scan_symlink_targets_and_type_changes(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    (repo / "link").write_text("clean\n")
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-q", "-m", "docs: link", env=env)
    git(repo, "push", "-q", "origin", "master", env=env)
    (repo / "link").unlink()
    (repo / "link").symlink_to("acmemart-host/data")             # file -> symlink (T)
    git(repo, "add", "-A", env=env)
    r = git(repo, "commit", "-m", "docs: relink", env=env, check=False)
    assert r.returncode != 0 and "HIT  link:1" in r.stdout + r.stderr
    allow = {**env, "DOPILOT_REDACTION_RULES": "none"}
    git(repo, "commit", "-q", "-m", "docs: relink", env=allow)
    p = git(repo, "push", "origin", "master", env=env, check=False)
    assert p.returncode != 0 and "link @" in p.stdout + p.stderr
    tree = run_tool("check", "--tree", env=dict(os.environ, **env), cwd=repo)
    assert tree.returncode == 1 and "HIT  link:1" in tree.stdout     # target, not followed


# ---------------------------------------------------------------- review round 2 edges
def test_hook_pre_push_scans_inner_tag_names(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    git(repo, "tag", "-a", "acmemart-inner", "-m", "clean inner", env=env)
    git(repo, "tag", "-a", "outer", "-m", "clean outer", "acmemart-inner", env=env)
    r = git(repo, "push", "origin", "outer", env=env, check=False)
    assert r.returncode != 0 and "tag refs/tags/outer (name) (path)" in r.stdout + r.stderr
    git(repo, "tag", "-d", "outer", "acmemart-inner", env=env)
    git(repo, "tag", "-a", "inner", "-m", "clean inner", env=env)
    git(repo, "tag", "-a", "outer", "-m", "clean outer", "inner", env=env)
    ok = git(repo, "push", "-q", "origin", "outer", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_scans_tags_that_point_at_blobs_and_trees(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)

    def obj(*args, data=None):
        e = dict(os.environ, **GIT_ENV, HOME=str(tmp_path))
        return subprocess.run(["git", "-C", str(repo), *args], input=data, env=e,
                              capture_output=True, text=True, check=True).stdout.strip()

    bad_blob = obj("hash-object", "-w", "--stdin", data="ACMEMART dump\n")
    git(repo, "tag", "data-blob", bad_blob, env=env)               # lightweight -> blob
    r = git(repo, "push", "origin", "data-blob", env=env, check=False)
    assert r.returncode != 0 and "tag refs/tags/data-blob -> blob" in r.stdout + r.stderr
    tree = obj("mktree", data=f"100644 blob {bad_blob}\tnotes.txt\n")
    git(repo, "tag", "-a", "data-tree", "-m", "clean", tree, env=env)  # annotated -> tree
    r = git(repo, "push", "origin", "data-tree", env=env, check=False)
    assert r.returncode != 0 and "HIT  notes.txt:1" in r.stdout + r.stderr
    clean = obj("hash-object", "-w", "--stdin", data="clean\n")
    git(repo, "tag", "ok-blob", clean, env=env)
    ok = git(repo, "push", "-q", "origin", "ok-blob", env=env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hook_pre_push_lets_sensitive_refs_be_deleted(tmp_path):
    repo, env = make_hooked_repo(tmp_path, write_rules(tmp_path / "r.tsv"))
    _remote(repo, tmp_path, env)
    git(repo, "branch", "fix-acmemart", env=env)
    git(repo, "push", "-q", "origin", "fix-acmemart",
        env={**env, "DOPILOT_REDACTION_RULES": "none"})            # leaked earlier
    gone = git(repo, "push", "origin", ":fix-acmemart", env=env, check=False)
    assert gone.returncode == 0, gone.stdout + gone.stderr          # removal allowed
    again = git(repo, "push", "origin", "fix-acmemart", env=env, check=False)
    assert again.returncode != 0 and "ref refs/heads/fix-acmemart" in again.stdout + again.stderr


def test_apply_tree_redacts_symlink_path_and_target_without_following(tmp_path):
    rules_file = write_rules(tmp_path / "r.tsv")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    (repo / "acmemart-link").symlink_to("acmemart-host/data")      # dangling on purpose
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: link")
    env = dict(os.environ, DOPILOT_REDACTION_RULES=str(rules_file))
    r = run_tool("apply-tree", env=env, cwd=repo)
    assert r.returncode == 0 and "renamed 1" in r.stderr + r.stdout
    link = repo / "site-q-link"
    assert link.is_symlink() and os.readlink(link) == "site-q-host/data"
    assert not (repo / "acmemart-link").exists() and not (repo / "acmemart-link").is_symlink()
    git(repo, "add", "-A")
    assert run_tool("check", "--tree", env=env, cwd=repo).returncode == 0
    again = run_tool("apply-tree", env=env, cwd=repo)
    assert "rewrote 0 text, renamed 0" in again.stdout + again.stderr
