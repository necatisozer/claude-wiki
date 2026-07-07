# tests/test_capture_completeness.py — run: python3 tests/test_capture_completeness.py
#
# WP4 "capture completeness" (S1, P1). Pins the decided semantics of the four capture-completeness
# rows so a session is never silently lost:
#   1. RECONCILE  — `maintain` records sessions whose transcript exists but the live hook missed,
#                   BOUNDED to (max(activated_at, last_compile) … now]; pre-activation sessions are
#                   NOT swept in (that would defeat "start empty").
#   2. BACKFILL   — `wiki backfill --dry-run` lists what WOULD be recorded + a rough cost estimate and
#                   writes NOTHING; a real run records them and is RESUMABLE (a re-run does the rest).
#   3. STALL      — a backlog of un-ingested sessions past the threshold surfaces a neutral count-only
#                   banner in BOTH `wiki status` and the digest.
#   4. SCHEMA     — an OLD data schema migrates forward via the MIGRATIONS chain; a NEWER-than-engine
#                   schema is REFUSED, never silently used.
#
# SAFETY: every byte of engine + session state lives in tempfile.mkdtemp() dirs. HOME is overridden per
# run so the session enumerator (~/.claude/projects = $HOME/.claude/projects) NEVER reads the real
# user's transcripts, and the live wiki (~/.claude/wiki) / ~/.claude/settings*.json are never touched.
# The `claude` LLM is faked by a shim on PATH. No credential-shaped literal appears here (every fake
# token is a plain invented word built inline).
import os, sys, json, glob, sqlite3, tempfile, subprocess, shutil, atexit
from datetime import datetime, timezone, timedelta
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

# An EMPTY throwaway HOME → PROJECTS is empty by default; a scenario that needs transcripts passes its
# own throwaway HOME. NOTHING here ever points the enumerator at the real ~/.claude.
_SAFE_HOME = mkdtemp("capcomp_safehome_")

# ---- fake `claude` shim: canned record body (never a real API call), built at runtime -------------
FAKE = mkdtemp("capcomp_fake_")
REC_BODY = FAKE / "rec_body.md"
REC_BODY.write_text(
    "Implemented the widget feature end to end.\n\n"
    "## Decisions\n- Chose approach A over B for clarity\n\n"
    "## Files touched\n- widget.py — core implementation\n\n"
    "## Outcomes\n- unit tests pass\n")
(FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import os, sys, json\n"
    "rf = os.environ.get('FAKE_CLAUDE_RESULT_FILE')\n"
    "result = open(rf).read() if rf else 'fallback body'\n"
    "print(json.dumps({'result': result, 'total_cost_usd': 0.001, 'is_error': False}))\n")
os.chmod(FAKE / "claude", 0o755)

_SCHEMA = """CREATE TABLE IF NOT EXISTS sessions(
    session_id TEXT PRIMARY KEY, project TEXT, transcript_path TEXT, first_seen TEXT,
    message_count INTEGER, last_mtime INTEGER, summarized_at TEXT, summarized_by TEXT,
    page_path TEXT, ingested_at TEXT, ingested_by TEXT, status TEXT, skip_reason TEXT,
    date TEXT, title TEXT, description TEXT)"""


def run_engine(args, wiki_home, home=None, result_file=REC_BODY):
    env = {**os.environ,
           "WIKI_HOME": str(wiki_home),
           "HOME": str(home if home is not None else _SAFE_HOME),
           "PATH": str(FAKE) + os.pathsep + os.environ["PATH"]}
    if result_file:
        env["FAKE_CLAUDE_RESULT_FILE"] = str(result_file)
    return subprocess.run([sys.executable, str(ENGINE)] + args,
                          capture_output=True, text=True, env=env)


def write_config(wiki_home, cfg):
    Path(wiki_home).mkdir(parents=True, exist_ok=True)
    (Path(wiki_home) / "config.json").write_text(json.dumps(cfg))


def write_transcript(home, sid, cwd, marker, mtime=None):
    """A minimal but substantive transcript (user prompt + assistant reply) under $HOME/.claude/
    projects/<dir>/<sid>.jsonl so the shared enumerator finds it. Optional explicit file mtime bounds
    which side of the reconcile window it lands on."""
    d = Path(home) / ".claude" / "projects" / "dash-proj"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (sid + ".jsonl")
    entries = [
        {"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "main",
         "timestamp": "2026-07-06T00:00:00Z",
         "message": {"role": "user", "content": "Please implement " + marker + " in this project"}},
        {"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": "2026-07-06T00:00:01Z",
         "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                     "content": [{"type": "text", "text": "Working on " + marker + " now, wiring it in."}]}},
    ]
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    if mtime is not None:
        os.utime(str(p), (mtime, mtime))
    return p


def ledger_row(wiki_home, sid, cols):
    dbp = Path(wiki_home) / "state" / "ledger.db"
    if not dbp.exists():
        return None
    db = sqlite3.connect(str(dbp))
    try:
        return db.execute("SELECT %s FROM sessions WHERE session_id=?" % ",".join(cols), (sid,)).fetchone()
    finally:
        db.close()


def ledger_count(wiki_home):
    dbp = Path(wiki_home) / "state" / "ledger.db"
    if not dbp.exists():
        return 0
    db = sqlite3.connect(str(dbp))
    try:
        return db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        db.close()


def journals(wiki_home):
    return glob.glob(str(Path(wiki_home) / "journal" / "**" / "*.md"), recursive=True)


# =============================================================================================
# 1. RECONCILE — 2 unrecorded sessions INSIDE the bound + 1 OUTSIDE (pre-activation). `maintain`
#    records the in-bound two and leaves the out-of-bound one untouched (bounded catch-up).
# =============================================================================================
W1 = mkdtemp("capcomp_recon_w_")
H1 = mkdtemp("capcomp_recon_h_")
CWD1 = "/Users/dev/proj"
act_dt = datetime.now(timezone.utc) - timedelta(days=2)
act_epoch = act_dt.timestamp()
# window_days: 0 → no now-window cap, so the bound is PURELY activated_at (deterministic for the test).
write_config(W1, {"enabled": True, "activated_at": act_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "reconcile": {"enabled": True, "window_days": 0}})
IN1 = "11111111-1111-4111-8111-111111111111"   # mtime AFTER activation → in bound
IN2 = "22222222-2222-4222-8222-222222222222"   # mtime AFTER activation → in bound
OUT1 = "33333333-3333-4333-8333-333333333333"  # mtime BEFORE activation → out of bound
write_transcript(H1, IN1, CWD1, "reconcileAlpha", mtime=act_epoch + 3600)
write_transcript(H1, IN2, CWD1, "reconcileBeta",  mtime=act_epoch + 7200)
write_transcript(H1, OUT1, CWD1, "reconcileOld",  mtime=act_epoch - 3600)

r = run_engine(["maintain"], W1, home=H1)
assert r.returncode == 0, r.stdout + r.stderr
for sid in (IN1, IN2):
    row = ledger_row(W1, sid, ["summarized_at", "page_path", "status"])
    assert row and row[0] and row[1] and row[2] is None, \
        "an in-bound missed session (%s) must be reconciled into a real ledger row: %r" % (sid, row)
assert ledger_row(W1, OUT1, ["session_id"]) is None, \
    "a pre-activation (out-of-bound) session must NOT be swept in by reconcile"
assert len(journals(W1)) == 2, "exactly the two in-bound sessions get journals: %r" % journals(W1)
print("ok 1: reconcile catches in-bound missed sessions, ignores pre-activation ones (bounded)")

# =============================================================================================
# 2. BACKFILL — --dry-run lists candidates + a cost estimate and writes NOTHING; a real run records
#    all of them; a second run is a resumable no-op (only the remainder, here none).
# =============================================================================================
W2 = mkdtemp("capcomp_bf_w_")
H2 = mkdtemp("capcomp_bf_h_")
write_config(W2, {"enabled": True, "backfill": {"pace_seconds": 0}})
B1 = "44444444-4444-4444-8444-444444444444"
B2 = "55555555-5555-4555-8555-555555555555"
B3 = "66666666-6666-4666-8666-666666666666"
for sid, mark in ((B1, "backfillOne"), (B2, "backfillTwo"), (B3, "backfillThree")):
    write_transcript(H2, sid, "/Users/dev/hist", mark)

# --- dry-run: lists + estimates, writes NOTHING ---
r = run_engine(["backfill", "--dry-run"], W2, home=H2)
assert r.returncode == 0, r.stdout + r.stderr
assert "3 session(s) WOULD be recorded" in r.stdout, "dry-run must count candidates: %r" % r.stdout
assert "est. LLM cost" in r.stdout and "ROUGH" in r.stdout, "dry-run must show a rough cost estimate: %r" % r.stdout
assert "wrote NOTHING" in r.stdout, r.stdout
assert journals(W2) == [], "dry-run must not write any journal"
assert ledger_count(W2) == 0, "dry-run must not add any ledger row"

# --- real run: records all 3 ---
r = run_engine(["backfill"], W2, home=H2)
assert r.returncode == 0, r.stdout + r.stderr
assert len(journals(W2)) == 3, "a real backfill must record every candidate: %r" % journals(W2)
for sid in (B1, B2, B3):
    row = ledger_row(W2, sid, ["summarized_at", "page_path"])
    assert row and row[0] and row[1], "backfill must record %s" % sid

# --- resumable: a re-run skips already-recorded sessions (no-op) ---
r = run_engine(["backfill"], W2, home=H2)
assert r.returncode == 0, r.stdout + r.stderr
assert "nothing to do" in r.stdout, "a re-run must resume (all already recorded → no-op): %r" % r.stdout
assert len(journals(W2)) == 3, "the resumed no-op run must write no new journals"
print("ok 2: backfill --dry-run writes nothing (lists + cost); real run records; re-run resumes")

# =============================================================================================
# 3. STALL — a backlog of un-ingested sessions past the threshold surfaces a neutral count-only
#    banner in BOTH `wiki status` and the digest (no session content in the banner).
# =============================================================================================
W3 = mkdtemp("capcomp_stall_w_")
write_config(W3, {"enabled": True, "ingest": {"stall_threshold": 3}, "digest": {"max_chars": 50000}})
(W3 / "state").mkdir(parents=True, exist_ok=True)
CONTENT_MARK = "stallcontentmarkerword"
conn = sqlite3.connect(str(W3 / "state" / "ledger.db"))
conn.execute(_SCHEMA)
for i in range(5):   # 5 un-ingested (ingested_at NULL) > threshold 3
    conn.execute(
        "INSERT OR REPLACE INTO sessions "
        "(session_id,project,summarized_at,page_path,date,title,description,ingested_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("stall%02d" % i, "proj", "2026-07-06T00:00:00", "journal/2026/07/stall%02d.md" % i,
         "2026-07-0%d" % (i + 1), "T", CONTENT_MARK + str(i), None))
conn.commit(); conn.close()

rs = run_engine(["status"], W3)
assert rs.returncode == 0, rs.stderr
sbanner = [l for l in rs.stdout.splitlines() if "awaiting ingest" in l]
assert sbanner, "`wiki status` must show the stall banner: %r" % rs.stdout
assert "5" in sbanner[0], "the status banner must carry the count"
assert CONTENT_MARK not in sbanner[0], "the status stall banner is count-only — no session content"

rd = run_engine(["digest", "--cwd", "/x/y/proj"], W3)
assert rd.returncode == 0, rd.stderr
dbanner = [l for l in rd.stdout.splitlines() if "awaiting ingest" in l]
assert dbanner, "the digest must show the stall banner: %r" % rd.stdout
assert "5" in dbanner[0], "the digest banner must carry the count"
assert CONTENT_MARK not in dbanner[0], "the digest stall banner is count-only — no session content"
print("ok 3: stalled-ingest banner (count only) surfaces in both status and digest")

# =============================================================================================
# 4a. SCHEMA GUARD — an OLD (v1) data dir migrates forward via the MIGRATIONS chain and proceeds.
# =============================================================================================
W4 = mkdtemp("capcomp_schema_old_w_")
H4 = mkdtemp("capcomp_schema_old_h_")   # empty projects → reconcile no-op; only the migration matters
write_config(W4, {"enabled": True, "schema_version": 1})
r = run_engine(["maintain"], W4, home=H4)
assert r.returncode == 0, r.stdout + r.stderr
cfg_after = json.loads((W4 / "config.json").read_text())
assert cfg_after.get("schema_version") == 2, \
    "an old (v1) schema must migrate forward to the engine schema: %r" % cfg_after
assert cfg_after.get("activated_at"), "the v1→v2 migration must stamp activated_at"
assert "migrated data v1" in r.stderr, "the migration must be logged: %r" % r.stderr
print("ok 4a: an old (v1) data dir migrates forward and the engine proceeds")

# =============================================================================================
# 4b. SCHEMA GUARD — a NEWER-than-engine data dir is REFUSED, not silently used or downgraded.
# =============================================================================================
W5 = mkdtemp("capcomp_schema_new_w_")
write_config(W5, {"enabled": True, "schema_version": 99})
r = run_engine(["ingest"], W5)
assert r.returncode == 3, "a newer-than-engine data dir must be refused (rc 3): rc=%r out=%r" % (r.returncode, r.stdout)
assert "refused" in r.stdout.lower() or "refusing" in r.stderr.lower(), (r.stdout, r.stderr)
cfg_new = json.loads((W5 / "config.json").read_text())
assert cfg_new.get("schema_version") == 99, "a refused newer dir must NOT be rewritten/downgraded: %r" % cfg_new
print("ok 4b: a newer-than-engine data dir is refused, not silently used")

print("PASS test_capture_completeness")
