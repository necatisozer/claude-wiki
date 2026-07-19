# tests/test_page_staleness.py — run: python3 tests/test_page_staleness.py
#
# v0.1.9 — REPORT-ONLY page staleness: lint flags an ACTIVE page whose newest evidence of freshness
# (frontmatter created:/updated: or the newest dated `- YYYY-MM-DD` Sources bullet) is older than the
# per-kind window (projects 60d default; topics OFF by default — durable external facts don't decay
# on a timer). Decided design constraints pinned here:
#   • the pass NEVER writes: no status flip, no engine-owned key, no commit — the findings dict and
#     report are the entire output surface;
#   • newest-of-all-dates wins (a fresh Sources bullet un-stales a page with an old updated:);
#   • future dates beyond 1 day of skew are IGNORED (a poisoned fold can't immortalize a page);
#   • non-active statuses (archived/stale/…) and `-sources` companions are exempt;
#   • malformed pages skip silently (advisory — never wedges the sweep);
#   • findings feed _lint_open_count.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# and ~/.claude/settings*.json are never read or written. No credential-shaped literals.
import os, sys, json, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="stale_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("stale_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_stale", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_stale", _loader))
_loader.exec_module(wiki)

TODAY = datetime.now(timezone.utc).date()
def d(days_ago):
    return (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")

def _fresh(prefix, cfg=None):
    w = _mkdtemp(prefix)
    (w / "pages" / "topics").mkdir(parents=True)
    (w / "pages" / "projects").mkdir(parents=True)
    (w / "state").mkdir()
    if cfg is not None:
        (w / "config.json").write_text(json.dumps(cfg))
    wiki.WIKI = w
    return w

def _page(w, rel, name, created, updated, src_dates, status="active", extra_fm=""):
    srcs = "\n".join("- %s · aaaa1111 · n" % s for s in src_dates) or "- undated bullet"
    (w / rel).write_text(
        "---\nname: %s\ndescription: d\ntype: %s\nslug: %s\ncreated: %s\nupdated: %s\n"
        "status: %s\n%s---\n# %s\n\nprose\n\n## Sources\n%s\n"
        % (name, "project" if "/projects/" in rel else "topic", Path(rel).stem,
           created, updated, status, extra_fm, name, srcs))

def _seed_sid(w):
    (w / "journal" / "2026" / "07").mkdir(parents=True, exist_ok=True)
    (w / "journal" / "2026" / "07" / "2026-07-06__x__aaaa1111.md").write_text(
        "---\nname: X\nsessionId: aaaa1111-0000-4000-8000-000000000000\ningested: false\n---\n# X\n\nn\n")

def snapshot(w):
    return sorted((str(p.relative_to(w)), p.read_bytes()) for p in w.rglob("*") if p.is_file())

# =============================================================================================
# 1. Old project flags with its age; fresh project doesn't; NEWEST date wins (old updated: but a
#    recent Sources bullet → not stale). Topics are OFF by default even when ancient.
# =============================================================================================
w = _fresh("st1_"); _seed_sid(w)
_page(w, "pages/projects/old.md", "Old", d(200), d(100), [d(150), d(100)])
_page(w, "pages/projects/fresh.md", "Fresh", d(200), d(3), [d(30)])
_page(w, "pages/projects/revived.md", "Revived", d(200), d(100), [d(150), d(5)])   # fresh bullet wins
_page(w, "pages/topics/ancient.md", "Ancient", d(400), d(400), [d(400)])
before = snapshot(w)
f, pages, rep = wiki.lint_deterministic()
assert f["stale"] == ["old(100d)"], "exactly the old project flags, with its age: %r" % f["stale"]
assert "Stale pages" in rep and "old(100d)" in rep, "the report must carry the finding"
assert snapshot(w) == before, "REPORT-ONLY: lint must not write a single byte to the wiki"
print("ok 1: old project flags, fresh + freshly-cited pass, topics off by default, zero writes")

# =============================================================================================
# 2. Future-date poison guard: `updated: 2099-…` is ignored (beyond skew), so the page's real age
#    comes from its Sources — and it flags. One day of clock skew IS tolerated.
# =============================================================================================
w = _fresh("st2_"); _seed_sid(w)
_page(w, "pages/projects/poison.md", "Poison", d(200), "2099-01-01", [d(150)])
_page(w, "pages/projects/skew.md", "Skew", d(200), d(-1), [d(150)])   # tomorrow = tolerated skew
f, _, _ = wiki.lint_deterministic()
assert f["stale"] == ["poison(150d)"], "a future updated: must not immortalize the page: %r" % f["stale"]
print("ok 2: future-dated frontmatter ignored (poison guard); one-day skew tolerated")

# =============================================================================================
# 3. Exemptions: non-active status (archived / user-semantic stale) and `-sources` companions never
#    flag, however old. A page with NO parseable date flags as '(no dated sources)'.
# =============================================================================================
w = _fresh("st3_"); _seed_sid(w)
_page(w, "pages/projects/archived.md", "Archived", d(400), d(400), [d(400)], status="archived")
_page(w, "pages/projects/dropped.md", "Dropped", d(400), d(400), [d(400)], status="stale")
_page(w, "pages/projects/big-sources.md", "Big — earlier sources", d(400), d(400), [d(400)])
_page(w, "pages/projects/undated.md", "Undated", "unknown", "garbage", [])
f, _, _ = wiki.lint_deterministic()
assert f["stale"] == ["undated(no dated sources)"], \
    "archived/user-stale/companion exempt; undated page flags as no-dated-sources: %r" % f["stale"]
print("ok 3: non-active + companions exempt; date-less page flagged advisorily")

# =============================================================================================
# 4. Config: per-kind windows — topics flag when explicitly enabled; projects can be disabled (0);
#    findings feed _lint_open_count.
# =============================================================================================
w = _fresh("st4_", cfg={"enabled": True, "lint": {"stale_projects_days": 0, "stale_topics_days": 30}})
_seed_sid(w)
_page(w, "pages/projects/old.md", "Old", d(200), d(100), [d(100)])
_page(w, "pages/topics/oldtopic.md", "Old Topic", d(200), d(90), [d(90)])
f, _, _ = wiki.lint_deterministic()
assert f["stale"] == ["oldtopic(90d)"], "explicit topics window flags topics; projects 0 = off: %r" % f["stale"]
assert wiki._lint_open_count(f) == wiki._lint_open_count({**f, "stale": []}) + 1, \
    "stale findings must feed the lint_open count"
print("ok 4: per-kind windows configurable; stale feeds lint_open")

print("PASS test_page_staleness")
