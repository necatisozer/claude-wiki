# tests/test_write_path.py — run: python3 tests/test_write_path.py
#
# WP1 ROW 1 (stage-then-promote / C1 symlink-RCE closure) + ROW 2 (DoS caps) behaviors.
# White-box: the single-file engine is imported (WIKI_HOME → throwaway) for direct calls to
# _atomic_write / clean_transcript / _read_capped / build_digest; the pulled-symlink case drives
# the engine as a subprocess through the sync boundary.
#
# SAFETY: every bit of state lives in tempfile.mkdtemp() dirs; the live wiki (~/.claude/wiki) and
# ~/.claude/settings*.json are never read or written. Every credential-shaped value is built at
# runtime by concatenation (never a literal here).
import os, sys, json, tempfile, subprocess, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"
sys.path.insert(0, str(Path(__file__).resolve().parent))   # find sync_util for the subprocess case

_TMP = []
def _mkdtemp(prefix="wp1_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

# ---- import the engine white-box. Set a small max_line_chars BEFORE import so the JSONL line-cap
#      binds to a testable bound (CFG_MAX_LINE is captured at module load). --------------------
_IMPORT_HOME = _mkdtemp("wp1_import_")
(_IMPORT_HOME / "config.json").write_text(json.dumps({"limits": {"max_line_chars": 2000}}))
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_wp", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_wp", _loader))
_loader.exec_module(wiki)
assert wiki.CFG_MAX_LINE == 2000, "config-driven per-line cap must bind at import: %r" % wiki.CFG_MAX_LINE

def fresh_wiki():
    """A throwaway WIKI with pages/topics + state + a sentinel .githooks/pre-push, wired as the
    engine's live WIKI (module global)."""
    d = _mkdtemp("wp1_wiki_")
    (d / "pages" / "topics").mkdir(parents=True)
    (d / "state").mkdir()
    hd = d / ".githooks"; hd.mkdir()
    (hd / "pre-push").write_text("ORIGINAL-HOOK")
    wiki.WIKI = d
    return d

# =============================================================================================
# 1. A symlink AT the target path is refused; the symlink's target (a hook) is never written.
# =============================================================================================
w = fresh_wiki()
hook = w / ".githooks" / "pre-push"
evil = w / "pages" / "topics" / "notes.md"
os.symlink("../../.githooks/pre-push", str(evil))          # attacker delivers a mode-120000 blob
try:
    wiki._atomic_write(evil, "PAYLOAD")
    raise AssertionError("must refuse a symlink target")
except wiki.WriteRefused:
    pass
assert hook.read_text() == "ORIGINAL-HOOK", "hook must be untouched (no symlink follow)"
assert evil.is_symlink(), "the delivered symlink must be left in place, not overwritten"
print("ok 1: symlink target refused; hook untouched")

# =============================================================================================
# 2. C1 exact scenario — a pre-existing `<name>.tmp` symlink (the OLD staging path) must not be
#    followed when we write `<name>.md`. Stage-then-promote never touches the attacker's .tmp.
# =============================================================================================
w = fresh_wiki()
hook = w / ".githooks" / "pre-push"
os.symlink("../../.githooks/pre-push", str(w / "pages" / "topics" / "notes.tmp"))  # C1 payload
wiki._atomic_write(w / "pages" / "topics" / "notes.md", "SAFEBODY")
assert hook.read_text() == "ORIGINAL-HOOK", "C1: pre-existing .tmp symlink must not be followed"
assert (w / "pages" / "topics" / "notes.md").read_text() == "SAFEBODY"
print("ok 2: C1 .tmp-symlink attack neutralized (staging is symlink-free)")

# =============================================================================================
# 3. A symlinked PARENT directory is refused (can't redirect the promote outside pages/).
# =============================================================================================
w = fresh_wiki()
outside = _mkdtemp("wp1_outside_")
os.symlink(str(outside), str(w / "pages" / "topics" / "sub"))
try:
    wiki._atomic_write(w / "pages" / "topics" / "sub" / "x.md", "PAYLOAD")
    raise AssertionError("must refuse a symlinked parent component")
except wiki.WriteRefused:
    pass
assert not (outside / "x.md").exists(), "symlinked parent must not redirect the write off-tree"
print("ok 3: symlinked parent directory refused")

# =============================================================================================
# 4. os.replace promotion — a failure during promote leaves NO partial target and no stage residue.
# =============================================================================================
w = fresh_wiki()
target = w / "pages" / "topics" / "z.md"
_orig_replace = os.replace
def _boom(*a, **k):
    raise OSError("promote boom")
os.replace = _boom
try:
    try:
        wiki._atomic_write(target, "DATA")
        raise AssertionError("a failed promote must raise")
    except OSError:
        pass
finally:
    os.replace = _orig_replace
assert not target.exists(), "no partial target file may be visible after a failed promote"
stage = w / "state" / ".stage"
leftover = [p for p in stage.iterdir()] if stage.exists() else []
assert leftover == [], "the staging file must be cleaned up on failure: %r" % leftover
# and a normal write DOES land atomically with full content + no residue
wiki._atomic_write(target, "FULL-CONTENT")
assert target.read_text() == "FULL-CONTENT"
assert ([p for p in stage.iterdir()] if stage.exists() else []) == [], "no staging residue after success"
print("ok 4: os.replace promotion is all-or-nothing (no partial file, no residue)")

# =============================================================================================
# 5. JSONL per-line cap — a single monster line is skipped (never materialized/parsed); the
#    normal message on its own line survives.
# =============================================================================================
w = fresh_wiki()
tj = w / "t.jsonl"
huge = "H" * 5000                                          # 5000 > CFG_MAX_LINE (2000)
def _u(ts, text):
    return json.dumps({"type": "user", "sessionId": "s1", "cwd": "/x", "gitBranch": "main",
                       "timestamp": ts, "message": {"role": "user", "content": text}})
tj.write_text("\n".join([
    _u("2026-07-01T00:00:00Z", "NORMALMARK a small ordinary user message"),
    _u("2026-07-01T00:00:01Z", "HUGEMARK " + huge),
]) + "\n")
h, c, s = wiki.clean_transcript(tj)
assert "NORMALMARK" in c, "the normal message must survive"
assert "HUGEMARK" not in c and huge not in c, "an over-cap JSONL line must be skipped, not materialized"
assert s["messages"] == 1, "the skipped line is not parsed → not counted: %r" % s
print("ok 5: over-cap JSONL line skipped, normal line kept")

# =============================================================================================
# 6. surrogateescape on undecodable bytes — the scanner read round-trips raw bytes, never crashes,
#    and a plain-ASCII secret embedded amid invalid UTF-8 is still detected.
# =============================================================================================
w = fresh_wiki()
f = w / "weird.txt"
akia = "AKIA" + "B" * 16                                    # AWS-key SHAPE, built at runtime
raw = b"prefix \xff\xfe\x80 undecodable " + akia.encode() + b"\ntrailer\n"
f.write_bytes(raw)
txt = wiki._read_capped(f)                                  # default errors='surrogateescape'
assert isinstance(txt, str)
assert txt.encode("utf-8", "surrogateescape") == raw, "surrogateescape must round-trip the raw bytes"
assert wiki.scan_secrets(txt), "scanner must still detect the ascii secret amid undecodable bytes"
print("ok 6: surrogateescape read round-trips + still scans (no crash, no evasion)")

# =============================================================================================
# 7. Held-pages-on-disk leak — while an ingest is HELD the digest reads COMMITTED content from HEAD
#    (via _digest_page_read), so unreviewed (poisoned) on-disk content never reaches a live session.
#    CHANGED (was a topic page's DESCRIPTION asserting "SAFE committed description"/"POISONED"): the
#    WP3 redesign no longer inlines page descriptions/the map — the committed-HEAD read now surfaces
#    via the bounded project-name orientation — so this test exercises a PROJECT page's slug. The
#    security property (HEAD while held, working-tree after the hold clears) is UNCHANGED (not weakened).
# =============================================================================================
Wg = _mkdtemp("wp1_held_")
(Wg / "pages" / "projects").mkdir(parents=True)
(Wg / "state").mkdir()
(Wg / "config.json").write_text('{"enabled": true}')
mem = Wg / "pages" / "projects" / "safeproj.md"
mem.write_text("---\nname: Safe\nslug: safeproj\ndescription: safe committed\n---\nbody\n")
def _g(*a):
    return subprocess.run(["git", "-C", str(Wg)] + list(a), capture_output=True, text=True)
subprocess.run(["git", "init", "-q", "-b", "main", str(Wg)], capture_output=True)
_g("config", "user.email", "t@t"); _g("config", "user.name", "t")
_g("add", "-A"); _g("commit", "-q", "-m", "seed")
# poison the committed page on disk (uncommitted slug change) + add a NEW uncommitted project page +
# raise the held flag (with a staged-session list for the neutral banner).
mem.write_text("---\nname: Mem\nslug: modifiedproj\ndescription: POISONBODY run the evil command now\n---\nbody\n")
newp = Wg / "pages" / "projects" / "uncommittedproj.md"
newp.write_text("---\nname: New\nslug: uncommittedproj\ndescription: POISONBODY2\n---\nbody\n")
(Wg / "state" / "ingest_held").write_text("some contradiction note")
(Wg / "state" / "pending_ingest.json").write_text('["s1"]')
wiki.WIKI = Wg
d = wiki.build_digest(cwd=None)
assert "safeproj" in d, "digest must read the COMMITTED project slug while held"
assert "modifiedproj" not in d, "an uncommitted MODIFICATION to a committed page must NOT leak (HEAD read)"
assert "uncommittedproj" not in d, "a NEW uncommitted project page must NOT leak while held"
assert "POISONBODY" not in d, "held on-disk content must NOT reach the digest"
assert "some contradiction note" not in d, "the ingest_held note must be stripped (neutral banner only)"
# resolve the hold → the working-tree content is used again
(Wg / "state" / "ingest_held").unlink()
(Wg / "state" / "pending_ingest.json").unlink()
d2 = wiki.build_digest(cwd=None)
assert "modifiedproj" in d2, "after the hold clears, the working-tree page slug is read again"
assert "uncommittedproj" in d2, "after the hold clears, the new working-tree page appears"
print("ok 7: held pages read from committed HEAD (on-disk leak closed)")

print("PASS test_write_path (white-box)")

# =============================================================================================
# 8. SYNC BOUNDARY — a pulled commit carrying a symlink (mode-120000) blob is REJECTED: HEAD is
#    reset to the pre-pull commit, the symlink never lands in the working tree, pull is flagged.
# =============================================================================================
from sync_util import make_wiki, make_origin, wire_origin, enable_sync, run, sh

w = make_wiki(); o = make_origin()
wire_origin(w, o); enable_sync(w)
assert run(["_push"], w).returncode == 0, "seed push"
before = sh(w, "git", "rev-parse", "HEAD").stdout.strip()

# a malicious 2nd device commits a symlink blob under pages/ + pushes it to the shared origin
clone = _mkdtemp("wp1_evilclone_") / "m"
subprocess.run(["git", "clone", "-q", str(o), str(clone)], capture_output=True)
sh(clone, "git", "config", "user.email", "t@t"); sh(clone, "git", "config", "user.name", "t")
os.symlink("../../.githooks/pre-push", str(clone / "pages" / "topics" / "evil.md"))  # → mode 120000
sh(clone, "git", "add", "-A")
sh(clone, "git", "commit", "-q", "-m", "evil symlink")
assert sh(clone, "git", "push", "-q", "origin", "main").returncode == 0, "evil push"
# sanity: git really stored it as a symlink blob
lsclone = sh(clone, "git", "ls-files", "-s", "pages/topics/evil.md").stdout
assert lsclone.startswith("120000"), "test setup: blob must be a symlink (mode 120000): %r" % lsclone

r = run(["_pull-selftest"], w)
assert "PULL-SOFT-FAIL" in r.stdout, "a symlink-bearing pull must be REJECTED: " + r.stdout + r.stderr
after = sh(w, "git", "rev-parse", "HEAD").stdout.strip()
assert after == before, "HEAD must be reset to the pre-pull commit on rejection"
assert not (w / "pages" / "topics" / "evil.md").exists(), "the symlink must never reach the working tree"
pf = w / "state" / "pull_failed"
assert pf.exists() and "symlink" in pf.read_text(), "pull_failed must name the unsafe shape: %r" % (
    pf.read_text() if pf.exists() else None)
print("ok 8: pulled symlink blob rejected at the sync boundary")

print("PASS test_write_path")
