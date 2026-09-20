# tests/test_lint_skip_unchanged.py — run: python3 tests/test_lint_skip_unchanged.py
#
# The SCHEDULED lint skips a corpus that has not changed since the last report. Re-linting an
# untouched wiki spends a whole-corpus `claude -p` re-deriving findings already on disk — waste on
# any wiki that isn't being folded into, and the steady state under record.mode "stage", where
# nothing reaches pages until you drain. Pinned here:
#   1. a manual `wiki lint` runs and stamps the corpus fingerprint (state/lint_corpus)
#   2. `wiki lint --if-due` over an UNCHANGED corpus makes NO model call and leaves the report alone
#   3. editing or adding a page makes it due again — the skip is content-addressed, not a latch
#   4. a manual `wiki lint` ALWAYS runs, unchanged or not (asking for it is the reason to re-read)
#   5. a FAILED semantic review does NOT stamp, so the next scheduled sweep retries it instead of
#      skipping a corpus whose review never happened
#
# SAFETY: all state in tempfile.mkdtemp() dirs; HOME overridden so the session enumerator never sees
# real transcripts and the live wiki is untouched. `claude` is a shim on PATH that can act as a
# TRIPWIRE (records that it ran) or fail on demand. No credential-shaped literals.
import os, sys, json, tempfile, subprocess, shutil, atexit
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

_SAFE_HOME = mkdtemp("lintskip_safehome_")

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

FAKE = mkdtemp("lintskip_fake_")
(FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import os, sys, json\n"
    "tw = os.environ.get('FAKE_CLAUDE_TRIPWIRE')\n"
    "if tw: open(tw, 'a').write('called\\n')\n"
    "if os.environ.get('FAKE_CLAUDE_FAIL'):\n"
    "    sys.stderr.write('simulated provider failure\\n'); sys.exit(1)\n"
    "rf = os.environ.get('FAKE_CLAUDE_RESULT_FILE')\n"
    "result = open(rf).read() if rf else '## Semantic review\\n- none\\n'\n"
    "print(json.dumps({'result': result, 'total_cost_usd': 0.001, 'is_error': False}))\n")
os.chmod(FAKE / "claude", 0o755)


def run(args, wiki_home, tripwire=None, fail=False):
    env = {**os.environ,
           "WIKI_HOME": str(wiki_home),
           "HOME": str(_SAFE_HOME),
           "PATH": str(FAKE) + os.pathsep + os.environ["PATH"]}
    env.pop("FAKE_CLAUDE_TRIPWIRE", None)
    env.pop("FAKE_CLAUDE_FAIL", None)
    if tripwire:
        env["FAKE_CLAUDE_TRIPWIRE"] = str(tripwire)
    if fail:
        env["FAKE_CLAUDE_FAIL"] = "1"
    return subprocess.run([sys.executable, str(ENGINE)] + args, capture_output=True, text=True,
                          env=env)


def git_wiki(prefix):
    w = mkdtemp(prefix)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=w)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=w)
    subprocess.run(["git", "config", "user.name", "t"], cwd=w)
    for sub in ("pages/topics", "pages/projects", "journal/2026/07", "state", "logs"):
        (w / sub).mkdir(parents=True, exist_ok=True)
    (w / "config.json").write_text(json.dumps(
        {"enabled": True, "lint": {"enabled": True, "cron": "0 20 * * 1"}}))
    (w / ".gitignore").write_text("state/\nlogs/\n*.db*\n")
    subprocess.run(["git", "add", "-A"], cwd=w)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=w)
    return w


def write_page(w, name, body):
    (w / "pages" / "topics" / name).write_text(
        "---\nname: %s\ndescription: a page about %s\ntype: topic\nstatus: active\n"
        "created: 2026-07-01\nupdated: 2026-07-01\n---\n\n%s\n"
        % (name[:-3], name[:-3], body))


def make_due(w):
    """Rewind the cron stamp so the next `lint --if-due` is due again (a week passing)."""
    (w / "state" / "last_lint").write_text("2020-01-01T00:00:00")


def fingerprint(w):
    p = w / "state" / "lint_corpus"
    return p.read_text().strip() if p.exists() else ""


W = git_wiki("lintskip_w_")
write_page(W, "alpha.md", "Alpha covers the retry path and its trade-offs in ordinary prose.")
TRIP = mkdtemp("lintskip_trip_") / "calls.log"

# ---- (1) a manual sweep runs and records the corpus identity -------------------------------------
run(["lint"], W, tripwire=TRIP)
check("manual lint: ran the semantic review", TRIP.exists())
check("manual lint: wrote the report", (W / "lint-report.md").exists())
fp1 = fingerprint(W)
check("manual lint: stamped the corpus fingerprint", len(fp1) == 64)

# ---- (2) scheduled + unchanged → no model call, report untouched ---------------------------------
report_before = (W / "lint-report.md").read_text()
TRIP.unlink()
make_due(W)
run(["lint", "--if-due"], W, tripwire=TRIP)
check("scheduled lint: skipped an unchanged corpus", not TRIP.exists())
check("scheduled lint: left the existing report alone",
      (W / "lint-report.md").read_text() == report_before)
check("scheduled lint: kept the fingerprint", fingerprint(W) == fp1)

# ---- (3) a changed page makes it due again -------------------------------------------------------
write_page(W, "alpha.md", "Alpha now also documents the backoff ceiling and why it was raised.")
make_due(W)
run(["lint", "--if-due"], W, tripwire=TRIP)
check("scheduled lint: a changed page re-runs the sweep", TRIP.exists())
fp2 = fingerprint(W)
check("scheduled lint: fingerprint moved with the corpus", fp2 != fp1 and len(fp2) == 64)

# a NEW page counts as a change too (not just an edit to a known one)
TRIP.unlink()
write_page(W, "beta.md", "Beta describes the queue drain and the ordering guarantee it relies on.")
make_due(W)
run(["lint", "--if-due"], W, tripwire=TRIP)
check("scheduled lint: a new page re-runs the sweep", TRIP.exists())

# ---- (3b) lint.skip_unchanged false opts out of the skip entirely --------------------------------
TRIP_OPT = mkdtemp("lintskip_opt_") / "calls.log"
run(["lint"], W, tripwire=TRIP_OPT)                      # bring the fingerprint up to date
TRIP_OPT.unlink()
(W / "config.json").write_text(json.dumps(
    {"enabled": True, "lint": {"enabled": True, "cron": "0 20 * * 1", "skip_unchanged": False}}))
make_due(W)
run(["lint", "--if-due"], W, tripwire=TRIP_OPT)
check("skip_unchanged false: scheduled sweep runs on an unchanged corpus", TRIP_OPT.exists())
(W / "config.json").write_text(json.dumps(
    {"enabled": True, "lint": {"enabled": True, "cron": "0 20 * * 1"}}))
TRIP_OPT.unlink()
make_due(W)
run(["lint", "--if-due"], W, tripwire=TRIP_OPT)
check("skip_unchanged default: skipping resumes when the key is removed", not TRIP_OPT.exists())

# ---- (4) a manual sweep always runs, unchanged or not --------------------------------------------
TRIP.unlink()
run(["lint"], W, tripwire=TRIP)
check("manual lint: runs even when the corpus is unchanged", TRIP.exists())

# ---- (5) a FAILED semantic review must not be stamped as done ------------------------------------
W2 = git_wiki("lintskip_w2_")
write_page(W2, "gamma.md", "Gamma explains the cache eviction policy and its failure modes.")
run(["lint"], W2, fail=True)
check("failed review: still wrote a deterministic report", (W2 / "lint-report.md").exists())
check("failed review: did NOT stamp the corpus", fingerprint(W2) == "")
TRIP2 = mkdtemp("lintskip_trip2_") / "calls.log"
make_due(W2)
run(["lint", "--if-due"], W2, tripwire=TRIP2)
check("failed review: the next scheduled sweep retries it", TRIP2.exists())
check("failed review: a successful retry stamps the corpus", len(fingerprint(W2)) == 64)

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("PASS test_lint_skip_unchanged")
