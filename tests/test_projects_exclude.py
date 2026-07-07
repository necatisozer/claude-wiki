# tests/test_projects_exclude.py — run: python3 tests/test_projects_exclude.py
#
# WP2 projects.exclude (record-time privacy). Pins the decided semantics: a session whose cwd
# falls under a configured `projects.exclude` path prefix is short-circuited in `record` BEFORE
# any content is read — no clean_transcript, no LLM call, no journal, no page change. Only a
# content-free skip marker (sid + status) lands in the local ledger so `wiki status` stays honest.
#
# SAFETY: every engine state dir is a tempfile.mkdtemp(); HOME is overridden per-test for the
# ~-expansion case; the live wiki (~/.claude/wiki) and ~/.claude/settings*.json are never touched.
# The `claude` LLM is faked by a shim on PATH that (a) records that it was invoked and (b) echoes
# its stdin (the prompt) into the journal body — so a NON-excluded session's transcript content
# demonstrably reaches disk, making "content nowhere under WIKI_HOME" a real discriminator, not a
# tautology. No credential-shaped literal appears in this file.
import os, sys, json, glob, sqlite3, tempfile, subprocess, shutil, atexit
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

# ---- fake `claude` shim: touch a sentinel when called + echo stdin (prompt) as the body --------
FAKE = mkdtemp("excl_fake_")
(FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import os, sys, json\n"
    "data = sys.stdin.read()\n"
    "s = os.environ.get('FAKE_CLAUDE_SENTINEL')\n"
    "if s:\n"
    "    open(s, 'a').write('called\\n')\n"
    "print(json.dumps({'result': data, 'total_cost_usd': 0.0, 'is_error': False}))\n")
os.chmod(FAKE / "claude", 0o755)

def run_engine(args, wiki_home, home=None, sentinel=None):
    env = {**os.environ,
           "WIKI_HOME": str(wiki_home),
           "PATH": str(FAKE) + os.pathsep + os.environ["PATH"]}
    if home is not None:
        env["HOME"] = str(home)
    if sentinel is not None:
        env["FAKE_CLAUDE_SENTINEL"] = str(sentinel)
    return subprocess.run([sys.executable, str(ENGINE)] + args,
                          capture_output=True, text=True, env=env)

def write_config(wiki_home, cfg):
    (wiki_home / "config.json").write_text(json.dumps(cfg))

def build_transcript(path, sid, cwd, marker):
    """A minimal but substantive transcript (a user prompt + an assistant reply) so the cleaner
    keeps content → a NON-excluded session actually records. `marker` rides in the user prompt."""
    entries = [
        {"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "main",
         "timestamp": "2026-07-06T00:00:00Z",
         "message": {"role": "user", "content": "Please help me with " + marker + " in this project"}},
        {"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": "2026-07-06T00:00:01Z",
         "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                     "content": [{"type": "text", "text": "Working on the " + marker + " change now."}]}},
    ]
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

def ledger_row(wiki_home, sid, cols):
    db = sqlite3.connect(str(Path(wiki_home) / "state" / "ledger.db"))
    try:
        return db.execute("SELECT %s FROM sessions WHERE session_id=?" % ",".join(cols), (sid,)).fetchone()
    finally:
        db.close()

def content_under(wiki_home, needle):
    """Return the first file under WIKI_HOME whose bytes contain `needle` (covers the sqlite
    ledger + logs too), else None. Proof that excluded content never reached disk."""
    nb = needle.encode()
    for root, _dirs, files in os.walk(str(wiki_home)):
        for fn in files:
            p = Path(root) / fn
            try:
                if nb in p.read_bytes():
                    return str(p)
            except OSError:
                pass
    return None

EXCLUDED = "/Users/necatisozer/dev/private"

# =============================================================================================
# 1. EXCLUDED — cwd under an excluded prefix → NO journal, NO LLM call, content-free skip marker,
#    and the transcript's distinctive content is nowhere under WIKI_HOME.
# =============================================================================================
W1 = mkdtemp("excl_w1_")
write_config(W1, {"enabled": True, "projects": {"exclude": [EXCLUDED]}})
T1 = mkdtemp("excl_t1_")
SID1 = "aaaa0001-0000-4000-8000-000000000001"
MARK1 = "ZmarkerExcludeTestZ"
tpath1 = T1 / "t.jsonl"
build_transcript(tpath1, SID1, EXCLUDED + "/secret-proj", MARK1)
sent1 = T1 / "claude_called"
r = run_engine(["record", "--session", SID1, "--transcript", str(tpath1),
                "--cwd", EXCLUDED + "/secret-proj", "--trigger", "manual"], W1, sentinel=sent1)
assert r.returncode == 0, r.stdout + r.stderr
assert not sent1.exists(), "excluded session must NOT invoke the LLM"
assert glob.glob(str(W1 / "journal" / "**" / "*.md"), recursive=True) == [], "no journal for excluded"
assert glob.glob(str(W1 / "pages" / "**" / "*.md"), recursive=True) == [], "no page change for excluded"
row = ledger_row(W1, SID1, ["status", "skip_reason", "page_path", "project",
                            "transcript_path", "summarized_at"])
assert row is not None, "an excluded session must still leave a local skip marker"
assert row[0] == "skipped" and row[1] == "excluded", row
assert row[2] is None and row[3] is None and row[4] is None and row[5] is None, \
    "skip marker must be content-free (no page_path/project/transcript_path/summarized_at): %r" % (row,)
hit = content_under(W1, MARK1)
assert hit is None, "excluded transcript content leaked to %s" % hit
print("ok 1: excluded session — no journal/page/LLM, content-free skip marker, content nowhere on disk")

# =============================================================================================
# 2. SIBLING — a session NOT under the excluded prefix (same config) records normally; and a path
#    that merely shares a string prefix (…/privatex) is NOT excluded (path-component boundary).
# =============================================================================================
W2 = mkdtemp("excl_w2_")
write_config(W2, {"enabled": True, "projects": {"exclude": [EXCLUDED]}})
T2 = mkdtemp("excl_t2_")
SID2 = "bbbb0002-0000-4000-8000-000000000002"
MARK2 = "ZmarkerSiblingZ"
tpath2 = T2 / "t.jsonl"
build_transcript(tpath2, SID2, "/Users/necatisozer/dev/public", MARK2)
sent2 = T2 / "claude_called"
r = run_engine(["record", "--session", SID2, "--transcript", str(tpath2),
                "--cwd", "/Users/necatisozer/dev/public", "--trigger", "manual"], W2, sentinel=sent2)
assert r.returncode == 0, r.stdout + r.stderr
assert sent2.exists(), "a non-excluded session must invoke the LLM"
j2 = glob.glob(str(W2 / "journal" / "**" / "*.md"), recursive=True)
assert len(j2) == 1, j2
row2 = ledger_row(W2, SID2, ["status", "page_path", "summarized_at"])
assert row2 is not None and row2[0] is None and row2[1] and row2[2], row2
assert content_under(W2, MARK2) is not None, "sanity: a recorded session's content DOES reach disk"

SID2B = "bbbb0002-0000-4000-8000-00000000002b"
tpath2b = T2 / "tb.jsonl"
build_transcript(tpath2b, SID2B, "/Users/necatisozer/dev/privatex", MARK2)
r = run_engine(["record", "--session", SID2B, "--transcript", str(tpath2b),
                "--cwd", "/Users/necatisozer/dev/privatex", "--trigger", "manual"], W2)
assert r.returncode == 0, r.stdout + r.stderr
rb = ledger_row(W2, SID2B, ["status", "page_path"])
assert rb is not None and rb[0] is None and rb[1], \
    "'/dev/privatex' shares a string prefix with '/dev/private' but is NOT under it — must record"
print("ok 2: sibling (and string-prefix-only) sessions record normally under the same config")

# =============================================================================================
# 3. ~-EXPANSION — an excluded prefix given as `~/private` matches a session under $HOME/private.
# =============================================================================================
W3 = mkdtemp("excl_w3_")
HOME3 = mkdtemp("excl_home3_")
write_config(W3, {"enabled": True, "projects": {"exclude": ["~/private"]}})
T3 = mkdtemp("excl_t3_")
SID3 = "cccc0003-0000-4000-8000-000000000003"
MARK3 = "ZmarkerTildeZ"
excl_cwd = str(HOME3 / "private" / "secret-proj")
tpath3 = T3 / "t.jsonl"
build_transcript(tpath3, SID3, excl_cwd, MARK3)
sent3 = T3 / "claude_called"
r = run_engine(["record", "--session", SID3, "--transcript", str(tpath3),
                "--cwd", excl_cwd, "--trigger", "manual"], W3, home=HOME3, sentinel=sent3)
assert r.returncode == 0, r.stdout + r.stderr
assert not sent3.exists(), "~/private must expand via $HOME and match a session under $HOME/private"
assert glob.glob(str(W3 / "journal" / "**" / "*.md"), recursive=True) == []
assert ledger_row(W3, SID3, ["status", "skip_reason"]) == ("skipped", "excluded")
assert content_under(W3, MARK3) is None
# positive control: a session OUTSIDE ~/private still records under the same ~-config
SID3B = "cccc0003-0000-4000-8000-00000000003b"
tpath3b = T3 / "tb.jsonl"
build_transcript(tpath3b, SID3B, str(HOME3 / "public" / "proj"), MARK3)
r = run_engine(["record", "--session", SID3B, "--transcript", str(tpath3b),
                "--cwd", str(HOME3 / "public" / "proj"), "--trigger", "manual"], W3, home=HOME3)
assert r.returncode == 0, r.stdout + r.stderr
assert len(glob.glob(str(W3 / "journal" / "**" / "*.md"), recursive=True)) == 1
print("ok 3: ~/private expands via $HOME and matches; a sibling under the same config still records")

# =============================================================================================
# 4. KEY ABSENT / EMPTY — behaves exactly as today (a normal session records).
# =============================================================================================
W4 = mkdtemp("excl_w4_")
write_config(W4, {"enabled": True})                                   # no `projects` key at all
T4 = mkdtemp("excl_t4_")
SID4 = "dddd0004-0000-4000-8000-000000000004"
tpath4 = T4 / "t.jsonl"
build_transcript(tpath4, SID4, "/Users/necatisozer/dev/anything", "ZmarkerAbsentZ")
r = run_engine(["record", "--session", SID4, "--transcript", str(tpath4),
                "--cwd", "/Users/necatisozer/dev/anything", "--trigger", "manual"], W4)
assert r.returncode == 0, r.stdout + r.stderr
assert len(glob.glob(str(W4 / "journal" / "**" / "*.md"), recursive=True)) == 1, "absent key → must record"

W4B = mkdtemp("excl_w4b_")
write_config(W4B, {"enabled": True, "projects": {"exclude": []}})     # present but empty
SID4B = "dddd0004-0000-4000-8000-00000000004b"
tpath4b = T4 / "tb.jsonl"
build_transcript(tpath4b, SID4B, "/Users/necatisozer/dev/anything", "ZmarkerEmptyZ")
r = run_engine(["record", "--session", SID4B, "--transcript", str(tpath4b),
                "--cwd", "/Users/necatisozer/dev/anything", "--trigger", "manual"], W4B)
assert r.returncode == 0, r.stdout + r.stderr
assert len(glob.glob(str(W4B / "journal" / "**" / "*.md"), recursive=True)) == 1, "empty list → must record"
print("ok 4: projects.exclude absent or empty → normal recording (behavior unchanged)")

print("PASS test_projects_exclude")
