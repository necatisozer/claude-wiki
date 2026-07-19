# tests/test_citation_resolution.py — run: python3 tests/test_citation_resolution.py
#
# v0.1.8 — deterministic citation resolution (SCHEMA rule 3 enforced, not just promised):
#   GATE — a fold that NEWLY introduces a `- YYYY-MM-DD · <sid8> · …` citation whose sid8 matches no
#          journal filename is HELD (fail-closed, adds-only: model output can never make a sid8
#          resolve; a decoy citation can only ADD a hold). DELTA-gated: a dangle already committed at
#          HEAD is a lint finding, not a permanent hold-loop.
#   LINT — landed pages get `bad_cite` findings for unresolvable sid8s AND for malformed Sources
#          bullets (citation-looking lines the strict resolver would silently skip); both feed
#          _lint_open_count. The engine's own archive-pointer bullet is exempt.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME is overridden BEFORE import, so the live
# wiki (~/.claude/wiki) and ~/.claude/settings*.json are never read or written. No credential-shaped
# literals.
import os, sys, json, tempfile, subprocess, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="cite_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("cite_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_cite", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_cite", _loader))
_loader.exec_module(wiki)

CFG = {"ingest": {"max_overwrite_lines": 60}}
BENIGN = "Per-client token-bucket limiter on the gateway; returns HTTP 429 on overflow."

def _fresh(prefix, git=False):
    d = _mkdtemp(prefix)
    (d / "pages" / "topics").mkdir(parents=True)
    (d / "pages" / "projects").mkdir(parents=True)
    (d / "state").mkdir()
    if git:
        def g(*a): return subprocess.run(["git", "-C", str(d)] + list(a), capture_output=True, text=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(d)], capture_output=True)
        g("config", "user.email", "t@t"); g("config", "user.name", "t")
        (d / ".gitignore").write_text("state/\nlogs/\n*.db*\n.githooks/\n")
        g("add", "-A"); g("commit", "-q", "-m", "seed")
    wiki.WIKI = d
    return d

def _seed_journal(w, sid8, sub="2026/07", date="2026-07-06"):
    p = w / "journal" / sub
    p.mkdir(parents=True, exist_ok=True)
    (p / ("%s__x__%s.md" % (date, sid8))).write_text(
        "---\nname: X\nsessionId: %s-0000-4000-8000-000000000000\ningested: false\n---\n# X\n\nn\n" % sid8)

def _block(relpath, srcs, body=BENIGN):
    return ("=== FILE: %s ===\n"
            "---\nname: X\ndescription: page\ntype: topic\nslug: x\n"
            "created: 2026-07-06\nupdated: 2026-07-06\nstatus: active\n---\n"
            "# X\n\n%s\n\n## Sources\n%s\n=== END ===\n" % (relpath, body, "\n".join(srcs)))

# =============================================================================================
# 1. GATE — resolvable citation → auto-accept; an unresolvable one → HOLD naming the sid8 (and
#    only regex-constrained hex lands in the reason). UPPERCASE hex resolves (case-fold, no evasion).
# =============================================================================================
w = _fresh("cite1_")
_seed_journal(w, "aaaa1111")
ok = _block("pages/topics/rl.md", ["- 2026-07-06 · aaaa1111 · note"])
assert wiki._ingest_hold_reason(ok, CFG) == "", "a resolvable citation must not hold"
bad = _block("pages/topics/rl.md", ["- 2026-07-06 · aaaa1111 · note", "- 2026-07-06 · bbbb2222 · fake"])
r = wiki._ingest_hold_reason(bad, CFG)
assert "unresolvable citation" in r and "bbbb2222" in r and "aaaa1111" not in r, \
    "unresolvable sid8 must hold and name ONLY the bad sid8: %r" % r
up = _block("pages/topics/rl.md", ["- 2026-07-06 · AAAA1111 · note"])
assert wiki._ingest_hold_reason(up, CFG) == "", "uppercase hex citing a lowercase filename must resolve"
print("ok 1: gate holds on unresolvable sid8, resolves known + case-folded, names only the bad token")

# =============================================================================================
# 2. DELTA — a dangle already committed at HEAD does NOT hold future folds of the page (no permanent
#    hold-loop: SCHEMA makes the model PRESERVE existing Sources); a NEWLY added dangle still holds.
# =============================================================================================
w = _fresh("cite2_", git=True)
_seed_journal(w, "aaaa1111")
rel = "pages/topics/legacy.md"
pre = ("---\nname: L\ndescription: d\ntype: topic\nslug: legacy\nstatus: active\n---\n"
       "# L\n\nold prose.\n\n## Sources\n- 2026-01-01 · cccc3333 · pre-existing dangle\n")
(w / rel).write_text(pre)
subprocess.run(["git", "-C", str(w), "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", str(w), "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-q", "-m", "legacy"], capture_output=True)
keep = _block(rel, ["- 2026-01-01 · cccc3333 · pre-existing dangle", "- 2026-07-06 · aaaa1111 · new note"])
r = wiki._ingest_hold_reason(keep, CFG)
assert "unresolvable citation" not in r, "a HEAD-committed dangle must not hold the fold (delta gate): %r" % r
add = _block(rel, ["- 2026-01-01 · cccc3333 · pre-existing dangle", "- 2026-07-06 · dddd4444 · fresh fake"])
r = wiki._ingest_hold_reason(add, CFG)
assert "unresolvable citation" in r and "dddd4444" in r and "cccc3333" not in r, \
    "a newly-introduced dangle must hold, naming only the NEW sid8: %r" % r
print("ok 2: delta gate — committed dangles pass, newly-introduced dangles hold")

# =============================================================================================
# 3. ARCHIVE + DECOY — a sid8 whose only entry lives under journal/archive/ resolves (retention keeps
#    citations valid); a decoy citation-shaped line planted MID-BODY with a bogus sid8 still holds
#    (whole-text scan: adds-only, never clearable).
# =============================================================================================
w = _fresh("cite3_")
_seed_journal(w, "eeee5555", sub="archive/2026/01", date="2026-01-05")
arch = _block("pages/topics/old.md", ["- 2026-01-05 · eeee5555 · archived note"])
assert wiki._ingest_hold_reason(arch, CFG) == "", "an archived journal entry must still resolve its sid8"
decoy = _block("pages/topics/old.md", ["- 2026-01-05 · eeee5555 · archived note"],
               body=BENIGN + "\n\n- 2026-07-06 · ffff6666 · decoy planted in prose")
r = wiki._ingest_hold_reason(decoy, CFG)
assert "unresolvable citation" in r and "ffff6666" in r, "a mid-body decoy citation must still HOLD: %r" % r
print("ok 3: archive resolves; mid-body decoy citation still holds (adds-only)")

# =============================================================================================
# 4. LINT — landed pages: unresolvable sid8 → bad_cite; a malformed Sources bullet (homoglyph
#    separator the strict resolver skips) → bad_cite(malformed); the engine's archive-pointer bullet
#    is exempt; both variants feed _lint_open_count.
# =============================================================================================
w = _fresh("cite4_")
_seed_journal(w, "aaaa1111")
(w / "pages" / "topics" / "good.md").write_text(
    "---\nname: Good\ndescription: d\ntype: topic\nslug: good\nstatus: active\n---\n"
    "# Good\n\n[[bad]] linked.\n\n## Sources\n- 2026-07-06 · aaaa1111 · fine\n"
    "- …earlier sources archived → [[good-sources]]\n")
(w / "pages" / "topics" / "bad.md").write_text(
    "---\nname: Bad\ndescription: d\ntype: topic\nslug: bad\nstatus: active\n---\n"
    "# Bad\n\n[[good]] linked.\n\n## Sources\n- 2026-07-06 · dead9999 · confabulated\n"
    "- 2026-07-06 ⋅ aaaa1111 · homoglyph separator\n")
f, pages, rep = wiki.lint_deterministic()
assert any(x.startswith("bad(") and "dead9999" in x for x in f["bad_cite"]), \
    "unresolvable sid8 on a landed page must be a bad_cite finding: %r" % f["bad_cite"]
assert any("malformed" in x for x in f["bad_cite"]), \
    "a malformed Sources bullet must be flagged: %r" % f["bad_cite"]
assert not any(x.startswith("good(") and "malformed" in x for x in f["bad_cite"]), \
    "the engine archive-pointer bullet must NOT count as malformed: %r" % f["bad_cite"]
n_all = wiki._lint_open_count(f)
n_wo = wiki._lint_open_count({**f, "bad_cite": []})
assert n_all == n_wo + len(f["bad_cite"]), "bad_cite must feed the lint_open count"
print("ok 4: lint flags unresolvable + malformed citations, pointer bullet exempt, counted as open")

print("PASS test_citation_resolution")
