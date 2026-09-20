# tests/test_ingest_orphan_row.py — run: python3 tests/test_ingest_orphan_row.py
#
# A ledger row can outlive its journal file: a record whose journal write landed but whose commit
# never did (sync broken at that moment), a restore, a manual cleanup. Two things went wrong when
# that happened on a live wiki, and both are pinned here:
#   1. CRASH — _neutralized_journal_entries raised FileNotFoundError, taking down the WHOLE batch.
#      The batch is rebuilt identically every run, so ONE orphaned row blocked ingest permanently.
#   2. SILENT LIE — the post-fold guard compared `_journal_mtime_ns(pp) == read_mtimes[sid]`, and a
#      missing file reads None at both ends, so the orphan was marked ingested: the ledger claimed
#      its content reached the pages when the fold never saw a byte of it.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; HOME overridden. `claude` is a shim on PATH.
import os, sys, json, sqlite3, tempfile, subprocess, shutil, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"
_TMP = []
def mkdtemp(prefix):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_SAFE_HOME = mkdtemp("orphan_home_")
FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

FAKE = mkdtemp("orphan_fake_")
# a fold result that writes one page — enough for the batch to "succeed"
(FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "cap = os.environ.get('FAKE_CLAUDE_CAPTURE')\n"
    "if cap: open(cap, 'a').write(sys.stdin.read())\n"
    "body = 'FILE: pages/topics/demo.md\\n---\\nname: demo\\ndescription: a demo topic page\\n"
    "type: topic\\nstatus: active\\ncreated: 2026-07-01\\nupdated: 2026-07-01\\n---\\n\\n"
    "## What this is\\nA demo page folded from the batch.\\n'\n"
    "print(json.dumps({'result': body, 'total_cost_usd': 0.001, 'is_error': False}))\n")
os.chmod(FAKE / "claude", 0o755)

CAPTURE = mkdtemp("orphan_cap_") / "prompts.txt"
def run(args, w):
    env = {**os.environ, "WIKI_HOME": str(w), "HOME": str(_SAFE_HOME),
           "PATH": str(FAKE) + os.pathsep + os.environ["PATH"],
           "FAKE_CLAUDE_CAPTURE": str(CAPTURE)}
    return subprocess.run([sys.executable, str(ENGINE)] + args, capture_output=True, text=True,
                          env=env, input="")

SCHEMA = """CREATE TABLE IF NOT EXISTS sessions(
    session_id TEXT PRIMARY KEY, project TEXT, transcript_path TEXT, first_seen TEXT,
    message_count INTEGER, last_mtime INTEGER, summarized_at TEXT, summarized_by TEXT,
    page_path TEXT, ingested_at TEXT, ingested_by TEXT, status TEXT, skip_reason TEXT,
    date TEXT, title TEXT, description TEXT)"""

w = mkdtemp("orphan_wiki_")
for sub in ("pages/topics", "pages/projects", "journal/2026/09", "state", "logs"):
    (w / sub).mkdir(parents=True, exist_ok=True)
(w / "config.json").write_text(json.dumps({"enabled": True, "ingest": {"enabled": True}}))
subprocess.run(["git", "init", "-q", "-b", "main"], cwd=w)
subprocess.run(["git", "config", "user.email", "t@t"], cwd=w)
subprocess.run(["git", "config", "user.name", "t"], cwd=w)
(w / ".gitignore").write_text("state/\nlogs/\n*.db*\n")

# one REAL journal entry, one ORPHAN row whose file was never written
real = "journal/2026/09/2026-09-19__real-entry__aaaaaaaa.md"
(w / real).write_text("---\nname: Real entry\ndescription: a real session\ntype: session\n"
                      "date: 2026-09-19\nsessionId: aaaaaaaa-0000-4000-8000-000000000001\n---\n\n"
                      "## What happened\nReal work that the fold should see.\n")
orphan = "journal/2026/09/2026-09-19__orphan__bbbbbbbb.md"       # deliberately NOT created
conn = sqlite3.connect(str(w / "state" / "ledger.db"))
conn.execute(SCHEMA)
for sid, pp in (("aaaaaaaa-0000-4000-8000-000000000001", real),
                ("bbbbbbbb-0000-4000-8000-000000000002", orphan)):
    conn.execute("INSERT INTO sessions (session_id,project,first_seen,summarized_at,page_path,date,"
                 "title,description) VALUES (?,?,?,?,?,?,?,?)",
                 (sid, "demo", "2026-09-19T00:00:00Z", "2026-09-19T00:00:00Z", pp, "2026-09-19",
                  "T", "d"))
conn.commit(); conn.close()
subprocess.run(["git", "add", "-A"], cwd=w)
subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=w)
check("setup: the orphan's file really is absent", not (w / orphan).exists())

r = run(["ingest"], w)
out = r.stdout + r.stderr
check("ingest: does not crash on the orphan", "FileNotFoundError" not in out and "Traceback" not in out)
check("ingest: reports the skip rather than failing silently",
      "missing" in (w / "logs" / "wiki.log").read_text())

# the batch still carried the REAL entry — skipping the orphan must not drop its healthy neighbours
prompts = CAPTURE.read_text() if CAPTURE.exists() else ""
check("ingest: the real entry still reached the fold prompt",
      "Real work that the fold should see" in prompts)
check("ingest: the orphan contributed nothing to the prompt", "bbbbbbbb =====" not in prompts)

conn = sqlite3.connect(str(w / "state" / "ledger.db"))
orphan_ing = conn.execute("SELECT ingested_at FROM sessions WHERE session_id=?",
                          ("bbbbbbbb-0000-4000-8000-000000000002",)).fetchone()[0]
conn.close()
check("ingest: the orphan is NOT marked ingested", orphan_ing is None)

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("PASS test_ingest_orphan_row")
