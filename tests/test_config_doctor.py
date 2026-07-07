# tests/test_config_doctor.py — run: python3 tests/test_config_doctor.py
#
# WP5 "doctor & config hardening" — pins the load-bearing rows:
#   1/2. CONFIG VALIDATION in doctor — an unknown key and a wrong-type value are each reported
#        (advisory, exit stays 0); a config.local.json that won't PARSE is CRITICAL (doctor exits
#        non-zero with a clear message — it was a silent swallow in load_config before WP5).
#   3.   config.local.json DEEP-merge — a partial `ingest.mode` override preserves sibling ingest.*
#        keys (a shallow .update would clobber them).
#   4.   FTS5 availability probe surfaces in doctor (wiki query depends on it).
#   5.   `wiki query --limit N` returns exactly N of >N matches.
#   6.   transcript-format DRIFT surfacing — doctor reads the cleaner's unknown-type tally.
#   7.   wiki.log size-cap ROTATION.
#   8.   claude-CLI output-contract check — a drifted `claude -p --output-format json` envelope is
#        flagged by `wiki doctor --claude-contract` (fake `claude` shim → no real API call).
#
# SAFETY: every byte of state lives in tempfile.mkdtemp() dirs; WIKI_HOME (and HOME, for the record
# path that enumerates ~/.claude/projects) are overridden per run, so the live ~/.claude/wiki and
# ~/.claude/settings*.json are NEVER read or written. No credential-shaped literal appears here.
import os, sys, json, tempfile, subprocess, shutil, atexit
from pathlib import Path
from sync_util import ENGINE

_TMP = []
def mkdtemp(prefix="wiki5_cfgdoc_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

def run(args, wiki, home=None, extra_env=None):
    env = {**os.environ, "WIKI_HOME": str(wiki)}
    if home is not None:
        env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, ENGINE] + list(args), capture_output=True, text=True, env=env)

def wiki(config):
    w = mkdtemp()
    (w / "config.json").write_text(json.dumps(config))
    return w

# ============================================================================================
# 1. CONFIG VALIDATION — unknown key + wrong-type value are each reported (advisory; exit stays 0).
# ============================================================================================
w = wiki({"enabled": True, "recrod": {"model": "x"}, "record": {"input_max_chars": "lots"}})
r = run(["doctor"], w)
assert r.returncode == 0, "advisory config issues must NOT gate doctor:\n" + r.stdout + r.stderr
assert "unknown key 'recrod'" in r.stdout, "doctor must flag an unknown key:\n" + r.stdout
assert "record.input_max_chars" in r.stdout and "should be int" in r.stdout, \
    "doctor must flag a wrong-type value:\n" + r.stdout
print("ok 1: doctor reports an unknown key + a wrong-type value (advisory)")

# ============================================================================================
# 2. config.local.json PARSE FAILURE → CRITICAL: doctor exits non-zero with a clear message.
# ============================================================================================
w = wiki({"enabled": True})
(w / "state").mkdir()
(w / "state" / "config.local.json").write_text('{"sync": {"enabled": true,,}}')   # trailing comma → invalid
r = run(["doctor"], w)
assert r.returncode != 0, "an unparseable config.local.json must make doctor exit non-zero:\n" + r.stdout
assert "config.local.json" in r.stdout and "invalid JSON" in r.stdout, \
    "the parse failure needs a clear message:\n" + r.stdout
print("ok 2: config.local.json parse failure is a critical doctor failure with a clear message")

# ============================================================================================
# 3. DEEP-MERGE — config.local.json setting ONLY ingest.mode preserves the other ingest.* keys.
# ============================================================================================
w = wiki({"enabled": True,
          "ingest": {"model": "sonnet", "mode": "auto", "max_sessions_per_run": 50, "enabled": True}})
(w / "state").mkdir()
(w / "state" / "config.local.json").write_text(json.dumps({"ingest": {"mode": "review"}}))
assert json.loads(run(["_config-get", "ingest.mode"], w).stdout) == "review", "the local override must apply"
# The sibling keys would be NULLED by a shallow update — deep-merge must keep them:
assert json.loads(run(["_config-get", "ingest.max_sessions_per_run"], w).stdout) == 50, \
    "deep-merge must preserve a sibling default (shallow update clobbers it)"
assert json.loads(run(["_config-get", "ingest.model"], w).stdout) == "sonnet", "sibling model must survive"
print("ok 3: config.local.json deep-merge preserves sibling keys in the overridden section")

# ============================================================================================
# 4. FTS5 probe surfaces in doctor.
# ============================================================================================
w = wiki({"enabled": True})
r = run(["doctor"], w)
assert "fts5" in r.stdout, "doctor must report FTS5 availability:\n" + r.stdout
assert ("available" in r.stdout) or ("UNAVAILABLE" in r.stdout), r.stdout
print("ok 4: doctor reports FTS5 availability")

# ============================================================================================
# 5. `wiki query --limit N` returns exactly N of >N matches.
# ============================================================================================
w = wiki({"enabled": True})
d = w / "pages" / "topics"; d.mkdir(parents=True)
for i in range(6):
    (d / ("doc%d.md" % i)).write_text("---\nname: Doc %d\n---\ndependency injection wiring note\n" % i)
capped = json.loads(run(["query", "dependency", "--json", "--limit", "3"], w).stdout)
assert len(capped) == 3, "expected exactly 3 results with --limit 3, got %d" % len(capped)
allhits = json.loads(run(["query", "dependency", "--json"], w).stdout)
assert len(allhits) == 6, "default (no --limit) should return all 6 matches, got %d" % len(allhits)
print("ok 5: wiki query --limit N caps results to N")

# ============================================================================================
# 6. transcript-format DRIFT surfacing in doctor (seed the tally the recorder writes).
# ============================================================================================
w = wiki({"enabled": True})
(w / "state").mkdir()
(w / "state" / "drift.json").write_text(
    json.dumps({"types": {"brand-new-type": 4}, "updated": "2026-07-07T00:00:00Z"}))
r = run(["doctor"], w)
dl = [l for l in r.stdout.splitlines() if "drift" in l]
assert dl and "brand-new-type" in dl[0], "doctor must surface unknown transcript entry types:\n" + r.stdout
print("ok 6: doctor surfaces transcript-format drift")

# ============================================================================================
# 7. wiki.log size-cap ROTATION (tiny cap via WIKI_LOG_MAX_BYTES; throwaway HOME — the record path
#    enumerates ~/.claude/projects, so HOME must not point at the real one).
# ============================================================================================
w = wiki({"enabled": True})
(w / "logs").mkdir()
(w / "logs" / "wiki.log").write_text("X" * 1000)
run(["record", "--session", "nosuch"], w, home=mkdtemp("wiki5_cfgdoc_home_"),
    extra_env={"WIKI_LOG_MAX_BYTES": "200"})
assert (w / "logs" / "wiki.log.1").exists(), "a log past the cap must rotate to wiki.log.1"
assert (w / "logs" / "wiki.log.1").stat().st_size == 1000, "the rotated generation keeps the old content"
assert (w / "logs" / "wiki.log").stat().st_size < 1000, "the live log restarts small after rotation"
print("ok 7: wiki.log rotates when it exceeds the cap")

# ============================================================================================
# 8. claude-CLI output-CONTRACT check — fake `claude` on PATH (no real API call). A drifted envelope
#    (missing the result/is_error fields the engine parses) is flagged; a good envelope passes.
# ============================================================================================
fake = mkdtemp("wiki5_cfgdoc_fake_")
(fake / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import os, json\n"
    "print(os.environ.get('FAKE_ENVELOPE') or json.dumps({'result': 'ok', 'is_error': False, 'type': 'result'}))\n")
os.chmod(fake / "claude", 0o755)
w = wiki({"enabled": True})
good_path = {"PATH": str(fake) + os.pathsep + os.environ["PATH"]}
rg = run(["doctor", "--claude-contract"], w, extra_env=good_path)
gline = [l for l in rg.stdout.splitlines() if "cli-contract" in l]
assert gline and "OK" in gline[0], "a well-formed envelope must pass the contract check:\n" + rg.stdout
drifted = dict(good_path); drifted["FAKE_ENVELOPE"] = json.dumps({"answer": "ok"})   # no result/is_error
rb = run(["doctor", "--claude-contract"], w, extra_env=drifted)
bline = [l for l in rb.stdout.splitlines() if "cli-contract" in l]
assert bline and ("drift" in bline[0].lower() or "missing" in bline[0].lower()), \
    "a drifted claude -p envelope must be flagged:\n" + rb.stdout
print("ok 8: doctor --claude-contract validates the claude -p output envelope shape")

print("PASS test_config_doctor")
