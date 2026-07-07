# tests/test_ingest_slug_escape.py — run: python3 tests/test_ingest_slug_escape.py
#
# Regression for the companion-split out-of-tree write (post-0.1.0 review, finding #1).
# The ingest page-split builds a `<slug>-sources` companion path from the LLM-authored frontmatter
# `slug`; a `slug: ../../../…/evil` escaped WIKI because _reject_symlinked_path returned "allowed"
# for any `WIKI/…/../..` target (its lexical parent-walk meets the literal WIKI component before the
# fs root, and it never rejected on realpath-escape). Two layered fixes are asserted here:
#   (A) _reject_symlinked_path now rejects any target whose realpath is outside WIKI (sound for EVERY
#       caller, not just this one), and
#   (B) _split_oversized_page refuses a path-shaped slug outright (defense-in-depth) —
# while a legitimate oversized page still splits into an in-WIKI companion (feature intact).
#
# SAFETY: all state lives in tempfile.mkdtemp() dirs; the live wiki (~/.claude/wiki) and
# ~/.claude/settings*.json are never read or written. No credential-shaped literals here.
import os, sys, json, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="slugesc_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

# ---- import the engine white-box (WIKI_HOME → throwaway) -------------------------------------
_IMPORT_HOME = _mkdtemp("slugesc_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_slugesc", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_slugesc", _loader))
_loader.exec_module(wiki)

def fresh_wiki():
    """A throwaway WIKI (as `base/wiki`) with pages/topics + state, plus an empty sibling `base/escape_canary`
    that MUST stay empty. Returns (W, canary). The `../../../escape_canary` slug below reaches the canary
    from pages/topics/ (topics→pages→wiki→base), so a working escape would land a file in it."""
    base = _mkdtemp("slugesc_base_")
    W = base / "wiki"
    (W / "pages" / "topics").mkdir(parents=True)
    (W / "state").mkdir()
    canary = base / "escape_canary"; canary.mkdir()
    wiki.WIKI = W
    return W, canary

def big_page(slug, nsources=200, body_lines=5):
    """An oversized (> 160-line) topic page whose `## Sources` block IS the bloat (many dated bullets,
    small body) — the exact shape _split_oversized_page acts on, so a normal slug genuinely spills a
    companion and pulls the main page back under the cap. The two escape/feature cases share this shape,
    so the ONLY difference between them is the slug."""
    src = ["## Sources"] + ["- 2026-01-%02d · abcd1234 · note %d" % (i + 1, i) for i in range(nsources)]
    body = ["filler body line %d" % i for i in range(body_lines)]
    return "\n".join(
        ["---", "name: Victim", "description: d", "type: topic", "slug: " + slug, "status: active", "---",
         "", "# Title", ""] + body + [""] + src + [""])

ESCAPE_SLUG = "../../../escape_canary/pwned"   # from pages/topics/: topics→pages→wiki→base/escape_canary

# =============================================================================================
# 1. ROOT CAUSE — _reject_symlinked_path / _atomic_write refuse a `../`-escape target directly,
#    independent of any caller-side slug check. Proves the guard itself is now sound.
# =============================================================================================
W, canary = fresh_wiki()
escape_target = W / "pages" / "topics" / "../../../escape_canary/direct.md"
try:
    wiki._reject_symlinked_path(escape_target)
    raise AssertionError("guard must reject a target whose realpath escapes WIKI")
except wiki.WriteRefused:
    pass
try:
    wiki._atomic_write(escape_target, "PWNED")
    raise AssertionError("_atomic_write must refuse the escape target")
except wiki.WriteRefused:
    pass
assert list(canary.iterdir()) == [], "nothing may be written outside WIKI: %r" % list(canary.iterdir())
# a normal in-tree write still works (guard didn't over-reject)
wiki._atomic_write(W / "pages" / "topics" / "ok.md", "FINE")
assert (W / "pages" / "topics" / "ok.md").read_text() == "FINE"
print("ok 1: write guard rejects `..`-escape target, still allows in-tree writes")

# =============================================================================================
# 2. THE BUG — an oversized page with a path-shaped `slug` must NOT spill a companion outside WIKI.
#    _split_oversized_page returns no companion; _finalize_ingest_pages writes nothing to the canary.
# =============================================================================================
W, canary = fresh_wiki()
victim_rel = "pages/topics/victim.md"
(W / victim_rel).write_text(big_page(ESCAPE_SLUG))
new, comp_rel, comp = wiki._split_oversized_page(victim_rel, (W / victim_rel).read_text(), 160)
assert comp_rel is None and comp is None, "a path-shaped slug must yield NO companion: %r" % (comp_rel,)

out = wiki._finalize_ingest_pages([victim_rel], {})
assert list(canary.iterdir()) == [], "companion split must not escape WIKI: %r" % list(canary.iterdir())
assert out == [victim_rel], "no out-of-tree companion may be appended to the written list: %r" % out
# belt-and-suspenders: no stray file anywhere above WIKI
assert not (W.parent / "escape_canary" / "pwned-sources.md").exists(), "escaped companion must not exist"
print("ok 2: oversized page with `../`-slug spills no companion, escapes nothing")

# =============================================================================================
# 3. FEATURE INTACT — an oversized page with a NORMAL slug still splits into an in-WIKI companion.
# =============================================================================================
W, canary = fresh_wiki()
good_rel = "pages/topics/bigtopic.md"
(W / good_rel).write_text(big_page("bigtopic"))
out = wiki._finalize_ingest_pages([good_rel], {})
comp = W / "pages" / "topics" / "bigtopic-sources.md"
assert comp.exists(), "a legitimate oversized page must still split into a companion"
assert "pages/topics/bigtopic-sources.md" in out, "the companion must be recorded in the written list: %r" % out
assert (W / good_rel).read_text().count("\n") + 1 <= 160, "the main page must drop under the line cap"
assert list(canary.iterdir()) == [], "the legitimate split stays inside WIKI"
print("ok 3: legitimate oversized page still splits into an in-WIKI companion")

print("PASS test_ingest_slug_escape")
