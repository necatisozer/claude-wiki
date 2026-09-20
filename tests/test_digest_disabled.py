# tests/test_digest_disabled.py — run: python3 tests/test_digest_disabled.py
#
# `digest.enabled: false` — CAPTURE-ONLY operation. The wiki keeps recording, reconciling and
# running its scheduled jobs; it just stops pushing anything into a session. Pinned here because
# the failure mode is subtle in both directions: a digest that keeps injecting after being turned
# off, or a "disable" that quietly takes capture down with it.
#   1. the SessionStart hook still emits a VALID hook payload, with an EMPTY additionalContext
#   2. `wiki digest` (non-hook) prints nothing
#   3. recording still works — capture is untouched
#   4. the compile-trigger still fires, so reconcile/ingest/lint stay on their schedule
#   5. re-enabling restores the digest (it is a switch, not a one-way door)
#   6. the default remains ON — nobody gets silently disabled by upgrading
#
# SAFETY: all state in tempfile.mkdtemp() dirs; HOME overridden so the enumerator never sees real
# transcripts. `claude` is a shim on PATH. No credential-shaped literals.
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

_SAFE_HOME = mkdtemp("dgoff_safehome_")
FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

FAKE = mkdtemp("dgoff_fake_")
(FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import os, json\n"
    "print(json.dumps({'result': 'Did the work.\\n\\n## Outcomes\\n- done\\n',"
    " 'total_cost_usd': 0.001, 'is_error': False}))\n")
os.chmod(FAKE / "claude", 0o755)


def run(args, wiki_home, home=None):
    env = {**os.environ, "WIKI_HOME": str(wiki_home),
           "HOME": str(home if home is not None else _SAFE_HOME),
           "PATH": str(FAKE) + os.pathsep + os.environ["PATH"]}
    return subprocess.run([sys.executable, str(ENGINE)] + args, capture_output=True, text=True,
                          env=env, input="")


def write_config(w, cfg):
    Path(w).mkdir(parents=True, exist_ok=True)
    (Path(w) / "config.json").write_text(json.dumps(cfg))


def write_transcript(home, sid, cwd):
    d = Path(home) / ".claude" / "projects" / "dash-proj"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (sid + ".jsonl")
    p.write_text("\n".join(json.dumps(e) for e in [
        {"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "main",
         "timestamp": "2026-07-06T00:00:00Z",
         "message": {"role": "user", "content": "Please implement the widget feature here"}},
        {"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": "2026-07-06T00:00:01Z",
         "message": {"role": "assistant", "model": "m",
                     "content": [{"type": "text", "text": "Wiring the widget in now."}]}},
    ]) + "\n")
    return p


OFF = {"enabled": True, "digest": {"enabled": False},
       "record": {"model": "haiku"}, "ingest": {"enabled": False}, "lint": {"enabled": False}}
SID = "22222222-3333-4444-8555-666666666661"

H, W = mkdtemp("dgoff_home_"), mkdtemp("dgoff_wiki_")
write_config(W, OFF)

# ---- (1)(2) nothing is injected, but the hook contract still holds -------------------------------
r = run(["digest", "--hook", "--cwd", "/work/demo"], W, home=H)
try:
    payload = json.loads(r.stdout)
    ok_shape = payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    ctx = payload["hookSpecificOutput"]["additionalContext"]
except Exception as e:
    ok_shape, ctx = False, "<unparseable: %s>" % e
check("hook: still emits a valid SessionStart payload", ok_shape)
check("hook: additionalContext is empty", ctx == "")
r = run(["digest", "--cwd", "/work/demo"], W, home=H)
check("plain digest: prints nothing", r.stdout.strip() == "")

# ---- (3) capture is untouched --------------------------------------------------------------------
t = write_transcript(H, SID, "/work/demo")
r = run(["record", "--session", SID, "--transcript", str(t), "--cwd", "/work/demo"], W, home=H)
db = Path(W) / "state" / "ledger.db"
row = None
if db.exists():
    c = sqlite3.connect(str(db))
    row = c.execute("SELECT summarized_at, page_path FROM sessions WHERE session_id=?",
                    (SID,)).fetchone()
    c.close()
check("capture: recording still works with the digest off", bool(row and row[0] and row[1]))
check("capture: the journal entry was written",
      bool(list((Path(W) / "journal").glob("**/*.md"))))

# ---- (4) the scheduled pipeline is still reachable ------------------------------------------------
r = run(["status"], W, home=H)
check("status: states the digest is off", "digest" in r.stdout and "OFF" in r.stdout)
r = run(["doctor"], W, home=H)
check("doctor: reports the silence as deliberate, not broken",
      "OFF by config" in r.stdout and r.returncode == 0)

# ---- (5) it is a switch, not a one-way door -------------------------------------------------------
write_config(W, dict(OFF, digest={"enabled": True}))
r = run(["digest", "--cwd", "/work/demo"], W, home=H)
check("re-enabled: the digest comes back", "Session-wiki memory" in r.stdout)

# ---- (6) the default is ON ------------------------------------------------------------------------
W2 = mkdtemp("dgoff_wiki2_")
write_config(W2, {"enabled": True, "ingest": {"enabled": False}, "lint": {"enabled": False}})
r = run(["digest", "--cwd", "/work/demo"], W2, home=H)
check("default: a config without the key still digests", "Session-wiki memory" in r.stdout)

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("PASS test_digest_disabled")
