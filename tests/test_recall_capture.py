# tests/test_recall_capture.py — run: python3 tests/test_recall_capture.py
#
# v0.1.10 — recall capture (Phase A of index convergence). Pins the decided design:
#   • ENGINE-COMPUTED: events come from the transcript's actual tool_use records (`wiki … query`
#     Bash calls + Reads/Greps of wiki files), never from any model output;
#   • hit/miss from the PAIRED tool_result — `no matches for` / `--json`'s `[]` = confirmed miss,
#     is_error / missing pairing = unknown (None), and only confirmed values count downstream;
#   • SANITIZED terms: ASCII-fold (Turkish sözleşme → sozlesme), [a-z0-9 -] whitelist, hyphen runs
#     collapsed — a captured term can never corrupt frontmatter or carry a secret/URL/instruction;
#   • the digest's literal `<terms>` placeholder is ignored; flags are dropped; ≤ 8 events/session;
#   • journal round-trip: the `recall:` line parses back intact and keys after it survive;
#   • status surface is COUNT-ONLY (terms are attacker-seedable and never displayed).
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# and ~/.claude/settings*.json are never read or written. No credential-shaped literals.
import os, sys, json, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="rc_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("rc_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_rc", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_rc", _loader))
_loader.exec_module(wiki)

W = _mkdtemp("rc_wiki_")
for sub in ("pages/topics", "pages/projects", "state", "journal"):
    (W / sub).mkdir(parents=True)
wiki.WIKI = W

def tu(tid, name, inp):
    return json.dumps({"type": "assistant", "sessionId": "cafe0123-0000-4000-8000-000000000000",
                       "timestamp": "2026-07-20T10:00:00Z",
                       "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})

def tr(tid, content, is_err=False):
    return json.dumps({"type": "user",
                       "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": tid, "content": content,
                            "is_error": is_err}]}})

def clean(lines):
    d = _mkdtemp("rc_tr_")
    p = d / "t.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return wiki.clean_transcript(p)

# =============================================================================================
# 1. Query capture + hit/miss pairing: miss ('no matches for'), hit (results), json-miss ('[]'),
#    error → unknown, unpaired → unknown. Placeholder + flags handled.
# =============================================================================================
header, cleaned, stats = clean([
    tu("t1", "Bash", {"command": 'wiki query "metro di" --json'}),
    tr("t1", "no matches for 'metro di'"),
    tu("t2", "Bash", {"command": "/usr/local/bin/wiki query kmp publishing"}),
    tr("t2", "1. [[kmp-publishing]] — klib publishing conventions"),
    tu("t3", "Bash", {"command": "wiki query nothing --json"}),
    tr("t3", "[]"),
    tu("t4", "Bash", {"command": "wiki query broken"}),
    tr("t4", "boom", True),
    tu("t5", "Bash", {"command": "wiki query interrupted never answered"}),
    tu("t6", "Bash", {"command": 'wiki query "<terms>"'}),          # digest suggestion text — not a search
    tu("t7", "Bash", {"command": "git status"}),                     # not a wiki query at all
])
r = header["recall"]
assert r[0] == {"q": "metro di", "hit": False}, "confirmed miss must pair: %r" % r
assert r[1] == {"q": "kmp publishing", "hit": True}, "confirmed hit must pair: %r" % r
assert r[2] == {"q": "nothing", "hit": False}, "--json '[]' is a confirmed miss: %r" % r
assert r[3] == {"q": "broken", "hit": None}, "an errored result stays unknown: %r" % r
assert r[4] == {"q": "interrupted never answered", "hit": None}, "unpaired stays unknown: %r" % r
assert len(r) == 5, "placeholder + non-query commands must not capture: %r" % r
print("ok 1: query capture with paired hit/miss; placeholder, flags, non-queries ignored")

# =============================================================================================
# 2. Sanitizer: Turkish folds not mangles; whitelist strips shell/injection shapes; hyphen runs
#    collapse; 60-char cap. Read/Grep of wiki files captured as relative paths; outside paths and
#    non-memory files aren't; duplicates dedupe; the 8-event cap holds.
# =============================================================================================
header, _, _ = clean([
    tu("s1", "Bash", {"command": 'wiki query "sözleşme"'}),
    tu("s2", "Bash", {"command": 'wiki query "a --- b; $(rm -rf /) https://evil.example"'}),
    tu("r1", "Read", {"file_path": str(W / "pages" / "topics" / "metro-di.md")}),
    tu("r2", "Read", {"file_path": str(W / "pages" / "topics" / "metro-di.md")}),   # dupe
    tu("r3", "Grep", {"path": str(W / "journal" / "2026")}),
    tu("r4", "Read", {"file_path": "/etc/hosts"}),
    tu("r5", "Read", {"file_path": str(W / "state" / "ledger.db")}),                 # not memory
])
r = header["recall"]
assert r[0]["q"] == "sozlesme", "Turkish must ASCII-fold, not mangle: %r" % r[0]
assert r[1]["q"] == "a - b rm -rf https evil example", "whitelist + hyphen-run collapse: %r" % r[1]
assert {"read": "pages/topics/metro-di.md"} in r and sum(1 for e in r if e.get("read") == "pages/topics/metro-di.md") == 1
assert {"read": "journal/2026"} in r, "Grep of a journal dir counts: %r" % r
assert not any(e.get("read", "").startswith(("..", "/")) for e in r)
assert not any("hosts" in str(e) or "ledger" in str(e) for e in r), "non-memory paths must not capture: %r" % r
big, _, _ = clean([tu("b%d" % i, "Bash", {"command": "wiki query q%d" % i}) for i in range(12)])
assert len(big["recall"]) == 8, "the per-session cap must hold: %d" % len(big["recall"])
print("ok 2: sanitizer folds/whitelists, wiki reads captured relative + deduped, cap holds")

# =============================================================================================
# 3. Journal round-trip: recall lands as ONE frontmatter line of compact JSON; parse_frontmatter
#    returns it intact; keys AFTER it (ingested/source) survive; json.loads round-trips; an empty
#    recall emits NO line at all.
# =============================================================================================
header["sessionId"] = "cafe0123-0000-4000-8000-000000000000"
header["title"] = "Recall Test"; header["models"] = {"m"}; header["ended"] = "2026-07-20T10:00:00Z"
rel = wiki.write_journal(header, "body line.", "/tmp/x.jsonl", desc="d")
text = (W / rel).read_text()
fm = wiki.parse_frontmatter(text)
back = json.loads(fm["recall"])
assert back == header["recall"], "recall must round-trip through frontmatter exactly"
assert fm.get("ingested") == "false" and fm.get("source"), "keys after recall: must survive"
assert "\nrecall: " in text and text.count("recall:") == 1, "exactly one recall line"
# distinct identity so this entry lands in its OWN file (same title+sid+date reuses the filename)
h2 = dict(header, recall=[], title="Empty Recall", sessionId="beef4567-0000-4000-8000-000000000000")
rel2 = wiki.write_journal(h2, "body.", "/tmp/x.jsonl", desc="d")
assert rel2 != rel and "recall:" not in (W / rel2).read_text(), "no recall events → no recall line"
print("ok 3: journal round-trip exact; empty capture emits nothing")

# =============================================================================================
# 4. Status surface is COUNT-ONLY: _recall_counts aggregates queries/misses/reads and never
#    returns term text. The case-2 header carried 2 queries (both unconfirmed) + 2 reads; the
#    empty-recall entry contributes nothing.
# =============================================================================================
jfiles = [str(p) for p in (W / "journal").rglob("*.md")]
nq, nmiss, nread = wiki._recall_counts(jfiles)
assert (nq, nmiss, nread) == (2, 0, 2), "counts over the written journal: %r" % ((nq, nmiss, nread),)
print("ok 4: status aggregation is count-only (2 queries, 0 confirmed misses, 2 reads)")

print("PASS test_recall_capture")
