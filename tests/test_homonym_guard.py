# tests/test_homonym_guard.py — run: python3 tests/test_homonym_guard.py
#
# v0.1.8 — fold-time homonym guard: page identity IS the filename stem, so a NEW page whose identity
# collides with an existing page (cross-kind exact stem, or near-identical normalized identity like
# `metro-di` ≈ `metrodi`) is HELD for review. Structurally FP-free for the normal case: folding INTO
# an existing page is exempt by construction (the guard only sees blocks whose target doesn't exist).
# The batch namespace folds forward (two colliding NEW pages in one fold are caught), and an internal
# error CONVERTS to a hold reason (fail-closed, never a crash loop, never silently fail-open).
# Lint gains a `homonym` net over EXISTING page identities for collisions that predate the guard.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# and ~/.claude/settings*.json are never read or written. No credential-shaped literals.
import os, sys, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="hom_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("hom_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_hom", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_hom", _loader))
_loader.exec_module(wiki)

CFG = {"ingest": {"max_overwrite_lines": 60}}
BENIGN = "Per-client token-bucket limiter on the gateway; returns HTTP 429 on overflow."

def _fresh(prefix):
    d = _mkdtemp(prefix)
    (d / "pages" / "topics").mkdir(parents=True)
    (d / "pages" / "projects").mkdir(parents=True)
    (d / "state").mkdir()
    # fixtures cite aaaa1111 — seed it so the citation gate stays quiet in these homonym-focused cases
    (d / "journal" / "2026" / "07").mkdir(parents=True)
    (d / "journal" / "2026" / "07" / "2026-07-06__x__aaaa1111.md").write_text(
        "---\nname: X\nsessionId: aaaa1111-0000-4000-8000-000000000000\ningested: false\n---\n# X\n\nn\n")
    wiki.WIKI = d
    return d

def _page(w, rel, name):
    (w / rel).write_text("---\nname: %s\ndescription: d\ntype: topic\nslug: %s\nstatus: active\n---\n"
                         "# %s\n\nprose\n\n## Sources\n- 2026-07-06 · aaaa1111 · n\n"
                         % (name, Path(rel).stem, name))

def _block(relpath, slug):
    return ("=== FILE: %s ===\n"
            "---\nname: N\ndescription: page\ntype: topic\nslug: %s\n"
            "created: 2026-07-06\nupdated: 2026-07-06\nstatus: active\n---\n"
            "# N\n\n%s\n\n## Sources\n- 2026-07-06 · aaaa1111 · note\n=== END ===\n"
            % (relpath, slug, BENIGN))

# =============================================================================================
# 1. Cross-kind exact-stem clash HOLDS; folding into the EXISTING page (same path) never does.
# =============================================================================================
w = _fresh("hom1_")
_page(w, "pages/projects/foo.md", "Foo")
r = wiki._ingest_hold_reason(_block("pages/topics/foo.md", "foo"), CFG)
assert "collides with existing pages/projects/foo.md" in r, "cross-kind stem clash must hold: %r" % r
r = wiki._ingest_hold_reason(_block("pages/projects/foo.md", "foo"), CFG)
assert "collides" not in r and "near-homonym" not in r, \
    "folding into the existing page itself must NOT trip the homonym guard: %r" % r
print("ok 1: cross-kind exact-stem clash holds; fold-into-existing is exempt")

# =============================================================================================
# 2. Normalized near-identity (`metro-di` vs `metrodi`, singular/plural) HOLDS for a NEW page;
#    an unrelated new page passes clean.
# =============================================================================================
w = _fresh("hom2_")
_page(w, "pages/topics/metro-di.md", "Metro DI")
r = wiki._ingest_hold_reason(_block("pages/topics/metrodi.md", "metrodi"), CFG)
assert "near-homonym" in r and "metro-di" in r, "norm collision must hold naming the existing page: %r" % r
r = wiki._ingest_hold_reason(_block("pages/topics/conventions.md", "conventions"), CFG)
assert r == "", "an unrelated new page must pass clean: %r" % r
_page(w, "pages/topics/convention.md", "Convention")
r = wiki._ingest_hold_reason(_block("pages/topics/conventions.md", "conventions"), CFG)
assert "near-homonym" in r, "singular/plural identity must hold: %r" % r
print("ok 2: normalized near-identity holds new pages; unrelated pages pass")

# =============================================================================================
# 3. INTRA-BATCH — two colliding NEW pages in ONE fold result are caught (namespace folds forward).
# =============================================================================================
w = _fresh("hom3_")
both = _block("pages/topics/metro-di.md", "metro-di") + _block("pages/topics/metrodi.md", "metrodi")
r = wiki._ingest_hold_reason(both, CFG)
assert "near-homonym" in r, "two colliding NEW pages in one batch must hold: %r" % r
print("ok 3: intra-batch collision caught")

# =============================================================================================
# 4. FAIL-CLOSED, NEVER A CRASH — an internal guard error converts to a hold reason.
# =============================================================================================
w = _fresh("hom4_")
_real = wiki._ident_norm
wiki._ident_norm = lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    r = wiki._ingest_hold_reason(_block("pages/topics/new.md", "new"), CFG)
finally:
    wiki._ident_norm = _real
assert "homonym guard error" in r, "an internal error must CONVERT to a hold (fail-closed): %r" % r
print("ok 4: internal guard error converts to a hold, never a crash or silent pass")

# =============================================================================================
# 5. LINT NET — near-identical EXISTING identities flagged (predates the guard / arrived via sync);
#    `-sources` companions exempt; counted in _lint_open_count.
# =============================================================================================
w = _fresh("hom5_")
_page(w, "pages/topics/metro-di.md", "Metro DI")
_page(w, "pages/topics/metrodi.md", "Metro DI Again")
_page(w, "pages/topics/metro-di-sources.md", "Metro DI — earlier sources")
f, pages, rep = wiki.lint_deterministic()
assert any("metrodi" in x and "metro-di" in x for x in f["homonym"]), \
    "existing near-homonym pair must be flagged: %r" % f["homonym"]
assert not any("sources" in x for x in f["homonym"]), "companions must be exempt: %r" % f["homonym"]
assert wiki._lint_open_count(f) > wiki._lint_open_count({**f, "homonym": []}), \
    "homonym findings must feed the lint_open count"
print("ok 5: lint homonym net flags existing pairs, companions exempt, counted as open")

print("PASS test_homonym_guard")
