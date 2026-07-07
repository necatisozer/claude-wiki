# tests/test_pipeline_golden.py — run: python3 tests/test_pipeline_golden.py
#
# Golden-transcript fixtures driving the engine's core pipeline (cleaner → record → ingest)
# with the LLM faked by a canned `claude` shim on PATH (the established fake-binary pattern
# from test_install_sh.py / sync_util.py). Every assert pins a REAL engine behavior so a broken
# cleaner/record/ingest fails — no tautologies.
#
# SAFETY: all engine state goes in tempfile.mkdtemp() dirs; the live wiki (~/.claude/wiki) and
# ~/.claude/settings*.json are never read or written. Any credential-shaped content is built at
# runtime by concatenation (never a literal in this file or any fixture).
import os, sys, json, sqlite3, tempfile, subprocess, shutil, atexit, glob
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"                 # __file__-derived, per the roadmap contract
FIXTURES = Path(__file__).resolve().parent / "fixtures"

CLEAN_SID = "0123abcd-c1ea-4001-9abc-def012345678"
JUNK_SID  = "99999999-9a9a-4002-9abc-000000000002"
INJ_SID   = "deadbeef-1a1a-4003-9abc-000000000003"
CLEAN_CWD = "/Users/necatisozer/dev/apigw"     # distinct from any WIKI_HOME → no reentrancy skip

_TMP = []
def _mkdtemp(prefix):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

# ---- import the single-file engine for direct, white-box cleaner assertions -----------------
# WIKI_HOME must point at a throwaway BEFORE import (module-level WIKI + CFG_* caps bind here).
_IMPORT_HOME = _mkdtemp("wikigold_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine", _loader))
_loader.exec_module(wiki)
# defaults (no config.json in the throwaway import home) — the bounds the monster test relies on
assert (wiki.CFG_USER, wiki.CFG_ASST, wiki.CFG_INPUT_MAX) == (1500, 1200, 60000), \
    "cleaner caps drifted from defaults: %s" % ((wiki.CFG_USER, wiki.CFG_ASST, wiki.CFG_INPUT_MAX),)

# ---- fake `claude` shim (canned JSON envelope) ----------------------------------------------
# WP3 two-phase ingest: ingest now makes up to TWO LLM calls per batch — a phase-① SELECT call
# (system prompt carries the marker WIKI_SELECT_PHASE) and a phase-② FILE-block call. The shim
# distinguishes them by that marker: SELECT → an empty selection block (safe: phase ② then folds no
# existing bodies and the batch's new pages are still written); otherwise → the canned result file.
# (In this file's ingest cases the wiki has no pages yet, so phase ① short-circuits without an LLM
# call — the two-call path is driven end-to-end by tests/test_two_phase_ingest.py.)
_FAKE = _mkdtemp("wikigold_fake_")
(_FAKE / "claude").write_text(
    "#!/usr/bin/env python3\n"
    "import os, sys, json\n"
    "mode = os.environ.get('FAKE_CLAUDE_MODE', 'ok')\n"
    "if mode == 'malformed_envelope':\n"
    "    sys.stdout.write('this is not a json envelope at all\\n'); sys.exit(0)\n"
    "if mode == 'error_envelope':\n"
    "    print(json.dumps({'is_error': True, 'result': 'boom'})); sys.exit(0)\n"
    "if 'WIKI_SELECT_PHASE' in ' '.join(sys.argv):\n"
    "    print(json.dumps({'result': '=== SELECTED PAGES ===\\n=== END ===',\n"
    "                      'total_cost_usd': 0.0, 'is_error': False})); sys.exit(0)\n"
    "rf = os.environ.get('FAKE_CLAUDE_RESULT_FILE')\n"
    "result = open(rf).read() if rf else 'fallback'\n"
    "print(json.dumps({'result': result, 'total_cost_usd': 0.0012, 'is_error': False}))\n")
os.chmod(_FAKE / "claude", 0o755)

def run_engine(args, wiki_home, result_file=None, mode="ok", cwd=None, input=None):
    env = {**os.environ,
           "WIKI_HOME": str(wiki_home),
           "PATH": str(_FAKE) + os.pathsep + os.environ["PATH"],
           "FAKE_CLAUDE_MODE": mode}
    if result_file:
        env["FAKE_CLAUDE_RESULT_FILE"] = str(result_file)
    return subprocess.run([sys.executable, str(ENGINE)] + args,
                          capture_output=True, text=True, env=env, input=input)

def ledger_row(wiki_home, sid, cols):
    db = sqlite3.connect(str(Path(wiki_home) / "state" / "ledger.db"))
    try:
        return db.execute("SELECT %s FROM sessions WHERE session_id=?" % ",".join(cols), (sid,)).fetchone()
    finally:
        db.close()

# =============================================================================================
# 1. CLEANER — clean.jsonl: keeps substantive text + tool actions, drops every kind of noise
# =============================================================================================
h, c, s = wiki.clean_transcript(FIXTURES / "clean.jsonl")

assert h["sessionId"] == CLEAN_SID
assert h["cwd"] == CLEAN_CWD
assert h["branch"] == "main"
assert h["title"] == "Add rate limiting to API gateway"          # harvested from the ai-title entry
assert h["models"] == {"claude-sonnet-4-6"}
assert h["tool_counts"] == {"Read": 1, "Edit": 1, "Write": 1, "Bash": 2}
assert h["files_touched"] == {"/Users/necatisozer/dev/apigw/gateway.py",
                              "/Users/necatisozer/dev/apigw/limiter.py"}
# exact stats — a cleaner that miscounts prompts/edits/commits/messages fails here
assert s["user_prompts"] == 1, s          # 3 user-side noise lines dropped, not counted
assert s["assistant_texts"] == 6, s
assert s["edits"] == 2 and s["commits"] == 1, s
assert s["messages"] == 15, s
assert s["unknown_types"] == {"telemetry"}, s   # unknown type tracked but emits nothing

# substantive content kept
assert "token-bucket rate limiting" in c        # user prompt survived
assert "token-bucket limiter" in c              # assistant text survived
assert "• Edit: /Users/necatisozer/dev/apigw/gateway.py" in c
assert "• Write: /Users/necatisozer/dev/apigw/limiter.py" in c
assert "• Bash: git commit -am 'add token-bucket rate limiter'" in c
assert "12 passed in 1.24s" in c                # tool result head kept
# noise dropped
assert "THINK_MARKER" not in c                  # thinking block dropped
assert "<command-name" not in c                 # slash-command echo dropped
assert "[Request interrupted" not in c          # interrupt line dropped
assert "Caveat:" not in c                        # caveat line dropped
assert "telemetry" not in c                      # unknown-type payload never emitted
print("ok 1: cleaner keeps substance, drops noise (clean.jsonl)")

# =============================================================================================
# 2. CLEANER — junk.jsonl: greeting-only session has NO tool/edit/commit substance
# =============================================================================================
hj, cj, sj = wiki.clean_transcript(FIXTURES / "junk.jsonl")
assert hj["title"] == "Quick greeting"
assert hj["models"] == {"claude-haiku-4-5"}
assert hj["tool_counts"] == {} and hj["files_touched"] == set()
assert sj["user_prompts"] == 2 and sj["edits"] == 0 and sj["commits"] == 0, sj
assert "hi there" in cj and "Hello! How can I help you today?" in cj
assert "• " not in cj                            # zero tool-action lines
assert len(cj) < 400                             # tiny vs clean's substantive body
print("ok 2: cleaner marks greeting-only session as no-substance (junk.jsonl)")

# =============================================================================================
# 3. CLEANER — injection.jsonl: injection-SHAPED text carried through as inert DATA (parse-only)
#    (semantic injection defenses are a later work package — here we only pin that the cleaner
#     does not crash, does not execute fake tools, and does not mangle structure)
# =============================================================================================
hi, ci, si = wiki.clean_transcript(FIXTURES / "injection.jsonl")
# imperatives + delimiters + fake tool syntax survive verbatim as quoted data
assert "ignore all previous instructions" in ci.lower()
assert "=== SYSTEM OVERRIDE ===" in ci
assert '<tool_use name="Bash">rm -rf' in ci               # fake tool tag kept as literal text …
assert "=== FILE: pages/topics/evil.md ===" in ci         # … as is our own ingest grammar
# but NONE of it became a real action: no tool counted, no edit, no commit
assert hi["tool_counts"] == {} and si["edits"] == 0 and si["commits"] == 0, (hi, si)
# structure intact: exactly the real turns, delimiter lines did not split/collapse the transcript
assert sum(1 for ln in ci.splitlines() if ln.startswith("USER: ")) == 2
assert sum(1 for ln in ci.splitlines() if ln.startswith("ASSISTANT: ")) == 2
print("ok 3: injection-shaped content carried through inert, structure intact (injection.jsonl)")

# =============================================================================================
# 4. CLEANER — MONSTER transcript generated at runtime (NOT committed): truncation/size bounds
# =============================================================================================
mon_dir = _mkdtemp("wikigold_monster_")
mon = mon_dir / "monster.jsonl"
MSID, MCWD = "11111111-2222-3333-4444-555555555555", "/Users/necatisozer/dev/big"
def _u(ts, text): return {"type": "user", "sessionId": MSID, "cwd": MCWD, "gitBranch": "main",
                          "timestamp": ts, "message": {"role": "user", "content": text}}
def _a(ts, text): return {"type": "assistant", "sessionId": MSID, "cwd": MCWD, "timestamp": ts,
                          "message": {"role": "assistant", "model": "claude-haiku-4-5",
                                      "content": [{"type": "text", "text": text}]}}
def _at(ts, tuid, cmd): return {"type": "assistant", "sessionId": MSID, "cwd": MCWD, "timestamp": ts,
                                "message": {"role": "assistant", "model": "claude-haiku-4-5",
                                            "content": [{"type": "tool_use", "id": tuid, "name": "Bash",
                                                         "input": {"command": cmd}}]}}
def _tr(ts, tuid, content): return {"type": "user", "sessionId": MSID, "cwd": MCWD, "timestamp": ts,
                                    "message": {"role": "user", "content": [{"type": "tool_result",
                                                "tool_use_id": tuid, "content": content, "is_error": False}]}}
mentries = [
    _u("2026-07-01T00:00:00Z", "LONGUSER" + "z" * 5000),      # single very long line → per-msg truncate
    _at("2026-07-01T00:00:01Z", "tb1", "echo hi"),
    _tr("2026-07-01T00:00:02Z", "tb1", "A" * 5000),           # long no-space blob → <binary/long …>
]
for i in range(3000):                                          # thousands of entries → force head_tail trim
    ts = "2026-07-01T00:%02d:%02dZ" % (i // 60 % 60, i % 60)
    mentries.append(_u(ts, "filler user message number %d about widgets" % i))
    mentries.append(_a(ts, "filler assistant reply number %d ok" % i))
with open(mon, "w") as f:
    for e in mentries:
        f.write(json.dumps(e) + "\n")
expected_msgs = sum(1 for e in mentries if e["type"] in ("user", "assistant"))

hm, cm, sm = wiki.clean_transcript(mon)
assert sm["messages"] == expected_msgs == 6003, sm            # every message counted, none dropped
assert len(cm) <= wiki.CFG_INPUT_MAX + 64, len(cm)            # whole-output size bound (head_tail)
assert "[trimmed" in cm                                       # the size-bound marker actually engaged
assert "<binary/long" in cm                                   # long no-space blob collapsed
assert "LONGUSER" in cm and ("z" * 5000) not in cm            # long line head kept, tail truncated
assert max(len(ln) for ln in cm.splitlines()) <= 1600         # per-message cap holds on every line
print("ok 4: monster transcript truncation + size bounds hold (%d messages)" % sm["messages"])

# =============================================================================================
# 5. CLEANER — credential-shaped case injected at RUNTIME into a tempdir copy (never a literal)
# =============================================================================================
akia = "AKIA" + "B" * 16                                       # AWS-key SHAPE, built by concatenation
assert wiki.scan_secrets(akia), "sanity: fake value must be credential-shaped"
sec_dir = _mkdtemp("wikigold_secret_")
sec = sec_dir / "clean_secret.jsonl"
sec.write_text((FIXTURES / "clean.jsonl").read_text() +
               json.dumps({"type": "user", "sessionId": CLEAN_SID, "cwd": CLEAN_CWD,
                           "timestamp": "2026-07-05T09:00:16Z",
                           "message": {"role": "user", "content": "For the record my access key is " + akia}}) + "\n")
hs, cs, ss = wiki.clean_transcript(sec)                        # must not crash on secret-bearing content
# WP1 ROW 1 (re-added cleaner-stage redactor, spec blocker #5): the cleaner now MASKS credential-shaped
# spans in its OUTPUT so no raw secret ever reaches the record/ingest LLM prompt. (Previously this
# asserted `akia in cs` on the theory redaction was push-gate-only; that expectation is now reversed.)
assert akia not in cs, "cleaner-stage redactor must mask the raw secret before any LLM sees it"
assert "AKIA" in cs, "the masked form (mask keeps a short prefix) should remain as evidence"
print("ok 5: cleaner-stage redactor masks runtime-injected credential-shaped content")

# =============================================================================================
# 6. RECORD — clean.jsonl → journal entry with the expected frontmatter + a real ledger row
# =============================================================================================
WA = _mkdtemp("wikigold_wa_")
rec_body = _FAKE / "rec_body.md"
rec_body.write_text(
    "Added a token-bucket rate limiter to the API gateway capping clients at 100 req/min.\n\n"
    "## Decisions\n- Chose token-bucket over fixed-window for smoother throttling\n\n"
    "## Files touched\n- gateway.py — wired limiter into the request path\n"
    "- limiter.py — new token-bucket implementation\n\n"
    "## Outcomes\n- pytest -q: 12 passed\n")
r = run_engine(["record", "--session", CLEAN_SID, "--transcript", str(FIXTURES / "clean.jsonl"),
                "--cwd", CLEAN_CWD, "--trigger", "manual"], WA, result_file=rec_body)
assert r.returncode == 0, r.stdout + r.stderr
journals = glob.glob(str(WA / "journal" / "**" / "*.md"), recursive=True)
assert len(journals) == 1, journals
jtext = Path(journals[0]).read_text()
fm = wiki.parse_frontmatter(jtext)
assert fm["name"] == "Add rate limiting to API gateway"        # title threaded from cleaner header
assert fm["sessionId"] == CLEAN_SID
assert fm["project"] == "apigw"                                # project_label(cwd)
assert fm["date"] == "2026-07-05" and fm["ended"] == "2026-07-05T09:00:15Z"
assert fm["model"] == "claude-sonnet-4-6"
assert "Read" in fm["tools"] and "Bash×2" in fm["tools"]       # tool census in frontmatter
assert fm["files_touched"] == "2"                              # count of edited files
assert fm["ingested"] == "false"                               # durable not-yet-ingested flag
assert fm["source"].endswith("clean.jsonl")
assert "token-bucket rate limiter" in jtext                    # the faked model body was written through
row = ledger_row(WA, CLEAN_SID, ["summarized_at", "page_path", "status", "title", "description"])
assert row is not None and row[0] and row[1], row              # summarized + page_path set
assert row[2] is None                                          # not skipped, not error
assert row[3] == "Add rate limiting to API gateway"
assert row[4].startswith("Added a token-bucket rate limiter")  # first body line → description
print("ok 6: record wrote journal frontmatter + ledger row (clean.jsonl)")

# =============================================================================================
# 7. RECORD — malformed envelope → rc 1, status='error', NO journal written
# =============================================================================================
WB = _mkdtemp("wikigold_wb_")
r = run_engine(["record", "--session", CLEAN_SID, "--transcript", str(FIXTURES / "clean.jsonl"),
                "--cwd", CLEAN_CWD, "--trigger", "manual"], WB, result_file=rec_body,
               mode="malformed_envelope")
assert r.returncode == 1, r.stdout + r.stderr
assert glob.glob(str(WB / "journal" / "**" / "*.md"), recursive=True) == []
er = ledger_row(WB, CLEAN_SID, ["status", "page_path", "summarized_at"])
assert er is not None and er[0] == "error" and er[1] is None, er
print("ok 7: record flags a malformed model envelope as error, writes no journal")

# =============================================================================================
# 8. RECORD — content-free transcript (all-dropped/noise) → rc 0, skipped, NO journal
# =============================================================================================
WC = _mkdtemp("wikigold_wc_")
EMPTY_SID = "empty001-0000-4000-8000-000000000000"
empty = WC / "empty.jsonl"                                      # built at runtime (all entries drop to nothing)
empty.write_text("\n".join(json.dumps(e) for e in [
    {"type": "summary", "summary": "prev"},
    {"type": "file-history-snapshot", "snapshot": {}},
    {"type": "system", "sessionId": EMPTY_SID, "content": "boot", "timestamp": "2026-07-06T00:00:00Z"},
    {"type": "user", "sessionId": EMPTY_SID, "cwd": "/Users/necatisozer/dev/x",
     "timestamp": "2026-07-06T00:00:01Z", "message": {"role": "user", "content": "[Request interrupted by user]"}},
    {"type": "assistant", "sessionId": EMPTY_SID, "cwd": "/Users/necatisozer/dev/x",
     "timestamp": "2026-07-06T00:00:02Z", "message": {"role": "assistant", "model": "claude-haiku-4-5",
      "content": [{"type": "thinking", "thinking": "only thinking, no text", "signature": "s"}]}},
]) + "\n")
r = run_engine(["record", "--session", EMPTY_SID, "--transcript", str(empty),
                "--cwd", "/Users/necatisozer/dev/x", "--trigger", "manual"], WC, result_file=rec_body)
assert r.returncode == 0, r.stdout + r.stderr
assert glob.glob(str(WC / "journal" / "**" / "*.md"), recursive=True) == []
sr = ledger_row(WC, EMPTY_SID, ["status", "skip_reason", "page_path"])
assert sr is not None and sr[0] == "skipped" and "empty" in (sr[1] or "") and sr[2] is None, sr
print("ok 8: record skips a content-free session (no LLM call, no journal)")

# =============================================================================================
# 9. INGEST — after record, fold journal → pages; write valid FILE-blocks, SKIP the malformed
#    block, complete the rest of the batch (one bad block never aborts the batch)
# =============================================================================================
ing_out = _FAKE / "ing_out.md"
ing_out.write_text(
    "=== FILE: pages/topics/rate-limiting.md ===\n"
    "---\nname: Rate limiting\ndescription: token-bucket limiter capping API clients at 100 req/min\n"
    "type: topic\nslug: rate-limiting\ncreated: 2026-07-05\nupdated: 2026-07-05\nstatus: active\n---\n"
    "# Rate limiting\n\nPer-client token-bucket limiter on the [[apigw]] gateway; HTTP 429 on overflow.\n\n"
    "## Sources\n- 2026-07-05 · 0123abcd · added token-bucket limiter\n"
    "=== END ===\n"
    "=== FILE: pages/projects/apigw.md ===\n"
    "---\nname: apigw\ndescription: API gateway service\ntype: project\nslug: apigw\n"
    "created: 2026-07-05\nupdated: 2026-07-05\nstatus: active\n---\n"
    "# apigw\n\nAPI gateway; now enforces [[rate-limiting]].\n\n"
    "## Sources\n- 2026-07-05 · 0123abcd · wired limiter into request path\n"
    "=== END ===\n"
    "=== FILE: pages/topics/../escape.md ===\n"                # MALFORMED: path traversal → skipped
    "this must never be written\n"
    "=== END ===\n"
    "=== FILE: secrets/leak.md ===\n"                          # MALFORMED: outside pages/topics|projects → skipped
    "this must never be written either\n"
    "=== END ===\n"
    "=== SUMMARY ===\ncreated: rate-limiting, apigw\nupdated: none\n"
    "soft_contradiction: none\nhard_contradiction: none\n")
r = run_engine(["ingest"], WA, result_file=ing_out)            # WA still holds the recorded clean session
assert r.returncode == 0, r.stdout + r.stderr
assert "wrote 2 pages" in r.stdout, r.stdout
# the two valid blocks landed …
rl = WA / "pages" / "topics" / "rate-limiting.md"
ap = WA / "pages" / "projects" / "apigw.md"
assert rl.is_file() and ap.is_file()
assert "Per-client token-bucket limiter" in rl.read_text()    # faked block content flowed through
assert "now enforces [[rate-limiting]]" in ap.read_text()
# … and neither malformed block escaped the pages/ tree
assert not (WA / "pages" / "escape.md").exists()
assert not (WA / "secrets").exists()
# ingest regenerated the index and staged the session for review
idx = (WA / "index.md").read_text()
assert "[[rate-limiting]]" in idx and "[[apigw]]" in idx
staged = json.loads((WA / "state" / "pending_ingest.json").read_text())
assert staged == [CLEAN_SID], staged
print("ok 9: ingest wrote valid pages, skipped malformed blocks, staged the batch")

print("PASS test_pipeline_golden")
