# tests/test_hook_entrypoints.py — the PRODUCTION entry path (hooks.json → engine) + review
# regressions. Until now the two hook entrypoints (`record --from-hook-json`, `digest --hook`)
# and bin/session_end_record.sh had zero coverage: a payload-key rename or a broken JSON envelope
# would pass the whole suite while breaking every real capture/digest injection.
#
# Also pins: find_transcript's /subagents/ exclusion, the `wiki index` staged-batch guard and
# `wiki reindex` last_mtime seeding (re-record-storm regression), the shlex-quoted pre-push hook,
# and the quotePath fix in the push-scan (non-ASCII binary filenames).
#
# SAFETY: all state in tempfile.mkdtemp() dirs; HOME/CLAUDE_CONFIG_DIR/WIKI_HOME overridden BEFORE
# import and for every subprocess, so the live ~/.claude is never read or written. The `claude`
# LLM is faked by a shim on PATH. No credential-shaped literals.
import os, sys, json, glob, time, sqlite3, tempfile, subprocess, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"
SH = ROOT / "bin" / "session_end_record.sh"

_TMP = []
def mkdtemp(prefix):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

# ---- fake HOME with a projects tree; engine imported white-box AFTER the env points at it -----
FAKE_HOME = mkdtemp("hook_home_")
CLAUDE_DIR = FAKE_HOME / ".claude"
PROJECTS = CLAUDE_DIR / "projects"
PROJECTS.mkdir(parents=True)
os.environ["HOME"] = str(FAKE_HOME)
os.environ["CLAUDE_CONFIG_DIR"] = str(CLAUDE_DIR)
_IMPORT_WIKI = mkdtemp("hook_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_WIKI)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_hooks", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_hooks", _loader))
_loader.exec_module(wiki)

FAKE = mkdtemp("hook_fake_")
(FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import sys, json\n"
    "data = sys.stdin.read()\n"
    "print(json.dumps({'result': 'Recorded the gateway limiter work.', "
    "'total_cost_usd': 0.0, 'is_error': False}))\n")
os.chmod(FAKE / "claude", 0o755)

def env_for(wiki_home):
    return {**os.environ, "WIKI_HOME": str(wiki_home),
            "PATH": str(FAKE) + os.pathsep + os.environ["PATH"]}

def write_transcript(path, sid, cwd):
    entries = [
        {"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "main",
         "timestamp": "2026-07-06T00:00:00Z",
         "message": {"role": "user", "content": "Please wire the rate limiter into the gateway"}},
        {"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": "2026-07-06T00:00:01Z",
         "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                     "content": [{"type": "text", "text": "Added the token-bucket limiter."}]}},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

def ledger_row(wiki_home, sid, cols):
    db = sqlite3.connect(str(Path(wiki_home) / "state" / "ledger.db"))
    try:
        return db.execute("SELECT %s FROM sessions WHERE session_id=?" % ",".join(cols), (sid,)).fetchone()
    finally:
        db.close()

# =============================================================================================
# 1. `record --from-hook-json` — the EXACT payload shape Claude Code's SessionEnd hook delivers
#    (session_id / transcript_path / cwd). A key rename here breaks every real capture.
# =============================================================================================
W1 = mkdtemp("hook_w1_")
SID1 = "aaaa1111-0000-4000-8000-000000000001"
T1 = PROJECTS / "proj-a" / (SID1 + ".jsonl")
write_transcript(T1, SID1, "/Users/necatisozer/dev/apigw")
payload = json.dumps({"session_id": SID1, "transcript_path": str(T1),
                      "cwd": "/Users/necatisozer/dev/apigw"})
r = subprocess.run([sys.executable, str(ENGINE), "record", "--from-hook-json", payload],
                   capture_output=True, text=True, env=env_for(W1))
assert r.returncode == 0, r.stdout + r.stderr
entries = glob.glob(str(W1 / "journal" / "**" / "*.md"), recursive=True)
assert len(entries) == 1, "hook-json record must write exactly one journal entry: %r" % entries
row = ledger_row(W1, SID1, ["summarized_at", "summarized_by", "page_path"])
assert row and row[0] and row[2], "ledger row must be summarized: %r" % (row,)
assert row[1] == "session_end", "hook trigger must be recorded as session_end: %r" % (row,)
print("ok 1: record --from-hook-json consumes the SessionEnd payload shape end-to-end")

# =============================================================================================
# 2. `digest --hook` — must emit the SessionStart hookSpecificOutput JSON envelope on stdout;
#    under WIKI_ENGINE (the engine's own claude -p subprocesses) the digest must be empty
#    (reentrancy guard).
# =============================================================================================
r = subprocess.run([sys.executable, str(ENGINE), "digest", "--hook"],
                   capture_output=True, text=True, env=env_for(W1),
                   input=json.dumps({"cwd": "/Users/necatisozer/dev/apigw"}))
assert r.returncode == 0, r.stdout + r.stderr
env_out = json.loads(r.stdout)   # a malformed envelope would break SessionStart injection
hso = env_out.get("hookSpecificOutput") or {}
assert hso.get("hookEventName") == "SessionStart", "envelope must target SessionStart: %r" % env_out
assert isinstance(hso.get("additionalContext"), str) and hso["additionalContext"].strip(), \
    "digest hook must inject non-empty context for a wiki with a recorded session"
r = subprocess.run([sys.executable, str(ENGINE), "digest", "--hook"],
                   capture_output=True, text=True,
                   env={**env_for(W1), "WIKI_ENGINE": "1"}, input="{}")
assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] == "", \
    "WIKI_ENGINE reentrancy must yield an empty digest:\n" + r.stdout
print("ok 2: digest --hook emits the SessionStart envelope; reentrancy guard yields empty context")

# =============================================================================================
# 3. bin/session_end_record.sh — the actual hooks.json command: consumes the payload on stdin,
#    spawns the engine DETACHED. Reentrancy (WIKI_ENGINE) and empty-payload paths exit clean
#    without spawning anything.
# =============================================================================================
W3 = mkdtemp("hook_w3_")
SID3 = "cccc3333-0000-4000-8000-000000000003"
T3 = PROJECTS / "proj-c" / (SID3 + ".jsonl")
write_transcript(T3, SID3, "/Users/necatisozer/dev/apigw")
sh_env = {**env_for(W3), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
payload3 = json.dumps({"session_id": SID3, "transcript_path": str(T3),
                       "cwd": "/Users/necatisozer/dev/apigw"})
r = subprocess.run(["bash", str(SH)], input=payload3, capture_output=True, text=True, env=sh_env)
assert r.returncode == 0, r.stdout + r.stderr
deadline = time.time() + 20   # the spawn is nohup-detached — poll for the journal it writes
while time.time() < deadline:
    if glob.glob(str(W3 / "journal" / "**" / "*.md"), recursive=True):
        break
    time.sleep(0.2)
assert glob.glob(str(W3 / "journal" / "**" / "*.md"), recursive=True), \
    "detached record must land a journal entry (see %s)" % (W3 / "logs" / "record.log")
W3B = mkdtemp("hook_w3b_")
r = subprocess.run(["bash", str(SH)], input=payload3, capture_output=True, text=True,
                   env={**env_for(W3B), "CLAUDE_PLUGIN_ROOT": str(ROOT), "WIKI_ENGINE": "1"})
assert r.returncode == 0 and not (W3B / "logs").exists(), \
    "WIKI_ENGINE reentrancy must exit before any spawn/mkdir"
r = subprocess.run(["bash", str(SH)], input="", capture_output=True, text=True,
                   env={**env_for(W3B), "CLAUDE_PLUGIN_ROOT": str(ROOT)})
assert r.returncode == 0 and not (W3B / "logs").exists(), "empty payload must exit clean, no spawn"
print("ok 3: session_end_record.sh spawns the detached record; reentrancy/empty-payload exit clean")

# =============================================================================================
# 4. find_transcript — resolves the PARENT session transcript by sid glob and must never match
#    a /subagents/ transcript with the same sid.
# =============================================================================================
SID4 = "dddd4444-0000-4000-8000-000000000004"
parent = PROJECTS / "proj-d" / (SID4 + ".jsonl")
sub = PROJECTS / "proj-d" / "subagents" / (SID4 + ".jsonl")
write_transcript(parent, SID4, "/x"); write_transcript(sub, SID4, "/x")
hit = wiki.find_transcript(SID4, "/x")
assert hit == str(parent), "must resolve the parent transcript, never /subagents/: %r" % hit
sub2 = PROJECTS / "proj-e" / "subagents" / ("eeee5555-0000-4000-8000-000000000005.jsonl")
write_transcript(sub2, "eeee5555-0000-4000-8000-000000000005", "/x")
assert wiki.find_transcript("eeee5555-0000-4000-8000-000000000005", "/x") is None, \
    "a sid whose ONLY transcript is a subagent's must resolve to None"
print("ok 4: find_transcript picks the parent and excludes /subagents/")

# =============================================================================================
# 5. Dispatch: `wiki index` respects the staged-batch quarantine; `wiki reindex` seeds
#    last_mtime/transcript_path from the on-disk transcript so a rebuilt ledger does NOT
#    re-record (and re-bill) every session whose transcript still exists.
# =============================================================================================
W5 = mkdtemp("hook_w5_")
(W5 / "pages" / "topics").mkdir(parents=True)
(W5 / "pages" / "topics" / "seed.md").write_text(
    "---\nname: Seed\ndescription: d\ntype: topic\nslug: seed\nstatus: active\n---\n# Seed\n")
r = subprocess.run([sys.executable, str(ENGINE), "index"], capture_output=True, text=True, env=env_for(W5))
assert r.returncode == 0 and "[[seed]]" in (W5 / "index.md").read_text(), r.stdout + r.stderr
(W5 / "state").mkdir(exist_ok=True)
(W5 / "state" / "pending_ingest.json").write_text("[]")
r = subprocess.run([sys.executable, str(ENGINE), "index"], capture_output=True, text=True, env=env_for(W5))
assert r.returncode == 1 and "staged/held" in r.stdout, \
    "`wiki index` must refuse while a batch is staged: %s" % (r.stdout + r.stderr)
(W5 / "state" / "pending_ingest.json").unlink()

SID6 = "ffff6666-0000-4000-8000-000000000006"
T6 = PROJECTS / "proj-f" / (SID6 + ".jsonl")
write_transcript(T6, SID6, "/x")
(W5 / "journal" / "2026" / "07").mkdir(parents=True)
(W5 / "journal" / "2026" / "07" / "2026-07-06__seedwork__ffff6666.md").write_text(
    "---\nname: Seed work\ndescription: d\ntype: session\nsessionId: %s\nproject: p\n"
    "date: 2026-07-06\nended: 2026-07-06T10:00:00Z\ningested: false\n---\n# Seed work\n\nnote\n" % SID6)
r = subprocess.run([sys.executable, str(ENGINE), "reindex"], capture_output=True, text=True, env=env_for(W5))
assert r.returncode == 0, r.stdout + r.stderr
row = ledger_row(W5, SID6, ["summarized_at", "last_mtime", "transcript_path"])
assert row and row[0], "reindex must mark the session summarized: %r" % (row,)
assert row[1] is not None and row[2] == str(T6), \
    "reindex must seed last_mtime/transcript_path (else reconcile re-records the LLM): %r" % (row,)
print("ok 5: index quarantine guard + reindex seeds last_mtime (no re-record storm)")

# =============================================================================================
# 6. Pre-push hook generation — device paths are shlex-quoted: a `$`/space in WIKI_HOME or the
#    engine path must neither expand nor split inside the generated shell.
# =============================================================================================
W6 = Path(mkdtemp("hook_w6_")) / "di$rty name"
(W6 / "state").mkdir(parents=True)
wiki.WIKI = W6
hook_path = wiki._write_prepush_hook()
hook_text = Path(hook_path).read_text()
assert "'%s'" % W6 in hook_text or "di\\$rty" in hook_text, \
    "WIKI path must be shell-quoted in the generated hook:\n" + hook_text
assert subprocess.run(["bash", "-n", str(hook_path)]).returncode == 0, "generated hook must parse"
export_line = next(l for l in hook_text.splitlines() if l.startswith("export WIKI_HOME="))
env_probe = subprocess.run(["bash", "-c", export_line + '; printf %s "$WIKI_HOME"'],
                           capture_output=True, text=True)
assert env_probe.stdout == str(W6), \
    "sourcing the hook must reproduce the exact WIKI_HOME (no $-expansion/splitting): %r" % env_probe.stdout
print("ok 6: pre-push hook shell-quotes device paths ($ and spaces survive)")

# =============================================================================================
# 7. Push-scan quotePath — a BINARY file with a non-ASCII name under pages/ must still produce
#    an attributed binary-refuse finding (git's default quotePath used to break the parse).
# =============================================================================================
W7 = mkdtemp("hook_w7_")
wiki.WIKI = Path(W7)
g = lambda *a: subprocess.run(["git", "-C", str(W7)] + list(a), capture_output=True, text=True)
subprocess.run(["git", "init", "-q", "-b", "main", str(W7)], capture_output=True)
g("config", "user.email", "t@t"); g("config", "user.name", "t")
(W7 / "pages" / "topics").mkdir(parents=True)
(W7 / "pages" / "topics" / "notizen-übersicht.bin").write_bytes(b"\x00\x01binary\x00payload")
g("add", "-A"); g("commit", "-q", "-m", "binary with non-ascii name")
findings = wiki._scan_range("HEAD")
bin_hits = [f for f in findings if f[1] == "binary_file"]
assert bin_hits and bin_hits[0][0].startswith("pages/") and "notizen" in bin_hits[0][0], \
    "binary-refuse must attribute the non-ASCII filename: %r" % (findings,)
print("ok 7: push-scan attributes binary findings for non-ASCII filenames (quotePath fix)")

print("PASS test_hook_entrypoints")
