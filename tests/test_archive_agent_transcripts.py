# tests/test_archive_agent_transcripts.py — run: python3 tests/test_archive_agent_transcripts.py
#
# _archive_agent_transcripts: the "full" scope of record.archive_transcripts — gzip copy of ONE session's
# `agent-*.jsonl` subagent sidechains into the untracked state/agent-transcripts/<sid>/ — off by
# default, byte-faithful when on, scoped to `<project>/<sid>/subagents/` (the real Claude Code
# layout: the directory supplies the attribution the filenames lack, so a neighbouring session's
# sidechains are never collected), idempotent when nothing changed, re-archiving a source that has
# since grown, surviving one unreadable sidechain mid-walk, and never raising on a bad source.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# is never read or written. No credential-shaped literals.
import gzip, os, sys, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="aat_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("aat_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_aat", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_aat", _loader))
_loader.exec_module(wiki)

W = _mkdtemp("aat_wiki_")
(W / "state").mkdir(parents=True)
wiki.WIKI = W

ARCHIVE_ROOT = W / "state" / "agent-transcripts"
ON = {"record": {"archive_transcripts": "full"}}
OFF = {"record": {"archive_transcripts": False}}
SESSION_ONLY = {"record": {"archive_transcripts": "session"}}
LEGACY_TRUE = {"record": {"archive_transcripts": True}}

SID = "11111111-2222-3333-4444-555555555555"
OTHER_SID = "99999999-8888-7777-6666-555555555555"
AGENT_A = b'{"type":"user","message":"sidechain a"}\n'
AGENT_B = b'{"type":"user","message":"sidechain b"}\n' * 500   # multi-KB: exercises the chunked read
SESSION = b'{"type":"user","message":"main session"}\n'
NEIGHBOUR = b'{"type":"user","message":"another session sidechain"}\n'

def _project():
    """A Claude Code project dir in its REAL shape: `<project>/<sid>.jsonl` beside a per-session
    `<project>/<sid>/subagents/agent-*.jsonl` directory — plus a second session's sidechain dir,
    which must never be collected."""
    p = _mkdtemp("aat_proj_")
    (p / ("%s.jsonl" % SID)).write_bytes(SESSION)
    subs = p / SID / "subagents"
    subs.mkdir(parents=True)
    (subs / "agent-aaaa1111.jsonl").write_bytes(AGENT_A)
    (subs / "agent-bbbb2222.jsonl").write_bytes(AGENT_B)
    other = p / OTHER_SID / "subagents"
    other.mkdir(parents=True)
    (other / "agent-cccc3333.jsonl").write_bytes(NEIGHBOUR)
    return p, p / ("%s.jsonl" % SID)

fails = []
def check(label, cond):
    print("%s %s" % ("ok  " if cond else "FAIL", label))
    if not cond:
        fails.append(label)

# =============================================================================================
# 1. Scope gate. Sidechains are the "full" scope ONLY: absent key, false, "session" and legacy
#    `true` must all leave this tier untouched — `true` especially, since an existing config
#    carrying it must not silently start archiving hundreds of MB more on upgrade.
# =============================================================================================
_, tpath = _project()
for label, cfg in (("absent key", {}), ("false", OFF), ("\"session\"", SESSION_ONLY),
                   ("legacy true", LEGACY_TRUE), ("junk value", {"record": {"archive_transcripts": "yes"}})):
    wiki._archive_agent_transcripts(tpath, SID, cfg)
    check("%s archives no sidechains" % label, not ARCHIVE_ROOT.exists())
check("_archive_mode maps legacy true to session", wiki._archive_mode(LEGACY_TRUE) == "session")
check("_archive_mode maps false to off", wiki._archive_mode(OFF) == "")
check("_archive_mode passes through full", wiki._archive_mode(ON) == "full")

# =============================================================================================
# 2. On: this session's sidechains are archived byte-faithfully under its own sid — while the
#    session transcript (that is _archive_transcript's tier) and a NEIGHBOURING session's
#    sidechain in the same project dir are both left alone.
# =============================================================================================
proj, tpath = _project()
ARCHIVE = ARCHIVE_ROOT / SID
wiki._archive_agent_transcripts(tpath, SID, ON)
got = sorted(p.name for p in ARCHIVE.glob("*.jsonl.gz"))
check("both sidechains archived", got == ["agent-aaaa1111.jsonl.gz", "agent-bbbb2222.jsonl.gz"])
with gzip.open(ARCHIVE / "agent-aaaa1111.jsonl.gz", "rb") as f:
    check("small sidechain is byte-faithful", f.read() == AGENT_A)
with gzip.open(ARCHIVE / "agent-bbbb2222.jsonl.gz", "rb") as f:
    check("multi-KB sidechain is byte-faithful", f.read() == AGENT_B)
check("neighbouring session gets no archive dir", not (ARCHIVE_ROOT / OTHER_SID).exists())
check("no temp file left behind", not any(p.name.startswith(".") for p in ARCHIVE.iterdir()))
check("archive is 0600 (pre-redaction text)",
      (ARCHIVE / "agent-aaaa1111.jsonl.gz").stat().st_mode & 0o777 == 0o600)
check("copy carries the SOURCE's mtime, not now()",
      (ARCHIVE / "agent-aaaa1111.jsonl.gz").stat().st_mtime ==
      (proj / SID / "subagents" / "agent-aaaa1111.jsonl").stat().st_mtime)

# =============================================================================================
# 3. Idempotent: a second pass over unchanged sources rewrites nothing, so a re-record of a long
#    session does not re-gzip every sidechain it already holds.
# =============================================================================================
before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in ARCHIVE.glob("*.jsonl.gz")}
wiki._archive_agent_transcripts(tpath, SID, ON)
after = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in ARCHIVE.glob("*.jsonl.gz")}
check("unchanged sources are not rewritten", before == after)

# =============================================================================================
# 4. A source that has grown since its copy IS re-archived (transcripts are append-only, so the
#    newer file is a superset — the stale copy must not win). Covers the truncated-copy case too:
#    staleness is mtime EQUALITY against the source, so a copy stamped older is always redone.
# =============================================================================================
grown = AGENT_A + b'{"type":"user","message":"appended later"}\n'
src = proj / SID / "subagents" / "agent-aaaa1111.jsonl"
src.write_bytes(grown)
os.utime(src, ns=(before["agent-aaaa1111.jsonl.gz"][0] + 10**9,) * 2)   # a later append
wiki._archive_agent_transcripts(tpath, SID, ON)
with gzip.open(ARCHIVE / "agent-aaaa1111.jsonl.gz", "rb") as f:
    check("grown source is re-archived", f.read() == grown)

# =============================================================================================
# 4b. One unreadable sidechain skips ONLY itself. cleanupPeriodDays deleting a file mid-walk is
#     the very race this tier exists to beat — it must not cost the sidechains still on disk.
# =============================================================================================
proj2, tpath2 = _project()
shutil.rmtree(ARCHIVE, ignore_errors=True)
blocked = proj2 / SID / "subagents" / "agent-aaaa1111.jsonl"
blocked.chmod(0o000)                                  # unreadable, and sorts first
try:
    wiki._archive_agent_transcripts(tpath2, SID, ON)
finally:
    blocked.chmod(0o600)
check("a later sidechain still archives after an unreadable one",
      (ARCHIVE / "agent-bbbb2222.jsonl.gz").exists())

# =============================================================================================
# 5. Never raises: a transcript path whose directory does not exist must be a silent no-op, since
#    archival runs inside record() and must never fail a record that already wrote its page.
# =============================================================================================
try:
    wiki._archive_agent_transcripts(_mkdtemp("aat_gone_") / "nope" / "x.jsonl", SID, ON)
    check("missing project dir does not raise", True)
except Exception as e:
    check("missing project dir does not raise (%r)" % e, False)

print("\n%s" % ("FAILED: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
