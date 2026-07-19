# tests/test_integrity_v015.py — v0.1.5 integrity-audit fixes (run: python3 tests/test_integrity_v015.py)
#   I2  sync-boundary shape gate now also rejects executables + any .githooks/ path (hook-injection)
#   I3/I5 ingest never advances the ledger past a FAILED git commit (auto batch + --accept)
#   I4  companion split derives its path from the file stem, and companion write-refusal (in the
#       companion test — see test_ingest_slug_escape.py; here we pin the shape gate + commit guards)
#
# SAFETY: HOME + WIKI_HOME overridden to throwaways BEFORE import; the live wiki is never touched.
# No credential-shaped literals — the fake executable/hook contents are inert.
import os, sys, json, shutil, tempfile, atexit, subprocess, sqlite3
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="iv_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

os.environ["HOME"] = str(_mkdtemp("iv_home_"))
os.environ["WIKI_HOME"] = str(_mkdtemp("iv_import_"))
_loader = importlib.machinery.SourceFileLoader("wiki_engine_iv", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_iv", _loader))
_loader.exec_module(wiki)

def _git(d, *a):
    return subprocess.run(["git", "-C", str(d)] + list(a), capture_output=True, text=True)

def fresh_git_wiki(prefix="iv_w_"):
    d = _mkdtemp(prefix)
    (d / "pages" / "topics").mkdir(parents=True)
    (d / "pages" / "projects").mkdir(parents=True)
    (d / "state").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(d)], capture_output=True)
    _git(d, "config", "user.email", "t@t"); _git(d, "config", "user.name", "t")
    (d / ".gitignore").write_text("state/\nlogs/\n*.db*\n.githooks/\n")
    (d / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\nslug: seed\n---\nbody\n")
    _git(d, "add", "-A"); _git(d, "commit", "-q", "-m", "seed")
    wiki.WIKI = d
    return d

# =============================================================================================
# I2 — the sync-boundary shape gate rejects symlink/submodule (existing) AND now executables +
#      any tracked .githooks/ path (a hook a hostile remote could plant fires on the next git op).
# =============================================================================================
w = fresh_git_wiki()
assert wiki._pulled_shape_findings() == [], "a clean data repo must pass the shape gate"

# plant a tracked executable page and a tracked hook, commit them (simulating a hostile remote tree)
exe = w / "pages" / "topics" / "evil.md"; exe.write_text("---\nname: E\nslug: e\n---\nx\n")
os.chmod(exe, 0o755)
(w / ".githooks").mkdir(exist_ok=True)
(w / ".githooks" / "pre-push").write_text("#!/bin/sh\necho pwned\n")
_git(w, "add", "-A", "-f")                       # -f: .gitignore normally hides .githooks
_git(w, "commit", "-q", "-m", "hostile tree")
bad = wiki._pulled_shape_findings()
assert any(b.startswith("executable:") for b in bad), "executable blob must be flagged: %r" % bad
assert any(b.startswith("hook:") for b in bad), "tracked .githooks path must be flagged: %r" % bad
print("ok I2: shape gate rejects executables + tracked hooks (hook-injection vector)")

# =============================================================================================
# I5 — _ingest_auto_batch must NOT advance the ledger when the git commit fails. Simulate a commit
#      failure by monkeypatching git_commit_paths to return a non-zero result; assert sessions stay
#      un-ingested and the function reports 0.
# =============================================================================================
w = fresh_git_wiki()
(w / "config.json").write_text(json.dumps({"enabled": True, "ingest": {"max_sessions_per_run": 50}}))
jrel = "journal/2026/07/2026-07-19__s__deadbeef.md"   # v0.1.8: filename sid8 resolves the fold's citation
(w / "journal" / "2026" / "07").mkdir(parents=True)
(w / jrel).write_text("---\nname: S\nsessionId: deadbeef-1a1a-4003-9abc-000000000009\ningested: false\n---\n# S\n\nx\n")
SID = "deadbeef-1a1a-4003-9abc-000000000009"
conn = wiki.ledger()
conn.execute("INSERT INTO sessions(session_id, project, page_path, summarized_at, summarized_by, date, "
             "title, description) VALUES(?,?,?,?,?,?,?,?)",
             (SID, "p", jrel, "2026-07-19T09:00:00", "haiku", "2026-07-19", "S", "x"))
conn.commit()

_FOLD = ("=== FILE: pages/topics/new.md ===\n---\nname: New\ndescription: d\ntype: topic\nslug: new\n"
         "created: 2026-07-19\nupdated: 2026-07-19\nstatus: active\n---\n# New\n\nfolded\n\n"
         "## Sources\n- 2026-07-19 · deadbeef · x\n=== END ===\n")
wiki._ingest_two_phase = lambda rows, model, cfg: (_FOLD, 0.0, {"pages/topics/new.md"}, [])

class _Fail:
    returncode = 1; stderr = "simulated commit failure"; stdout = ""
_real_commit = wiki.git_commit_paths
wiki.git_commit_paths = lambda *a, **k: _Fail()
try:
    n = wiki._ingest_auto_batch(wiki.load_config(), conn)
finally:
    wiki.git_commit_paths = _real_commit
assert n == 0, "a failed commit must report 0 sessions ingested, not len(rows): %r" % n
row = conn.execute("SELECT ingested_at FROM sessions WHERE session_id=?", (SID,)).fetchone()
assert row[0] is None, "the ledger must NOT mark a session ingested when the commit failed: %r" % (row,)
conn.close()
print("ok I5: ingest does not advance the ledger past a failed git commit")

print("PASS test_integrity_v015")
