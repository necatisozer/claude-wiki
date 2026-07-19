# tests/test_ingest_write_fixes.py — run: python3 tests/test_ingest_write_fixes.py
#
# v0.1.8 — three write-path hardenings:
#   (1) parse_frontmatter delimiter is LINE-ANCHORED: a value containing "---" mid-line can no longer
#       truncate the machine-read block and silently drop load-bearing keys (ingested:/sessionId:).
#   (2) fold-write description cap: _finalize_ingest_pages truncates an over-cap frontmatter
#       description deterministically (same transform record applies), so desc_long stops recurring.
#   (3) companion-merge: a re-split APPENDS newly-moved citations to an existing `<slug>-sources`
#       companion — never overwrites it (the overwrite deleted every previously-archived citation).
#   (+) git_commit_paths with EXACT paths leaves an unrelated dirty page uncommitted — the mechanism
#       behind the auto-ingest exact-path commit (a broad `pages` pathspec swept hand-edits in).
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# and ~/.claude/settings*.json are never read or written. No credential-shaped literals.
import os, sys, subprocess, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="iwf_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("iwf_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_iwf", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_iwf", _loader))
_loader.exec_module(wiki)

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

# =============================================================================================
# 1. parse_frontmatter — line-anchored delimiter: a mid-line "---" in a value no longer truncates
#    the block; keys after it survive. A body horizontal-rule line stays out of the frontmatter.
# =============================================================================================
fm = wiki.parse_frontmatter("---\nname: A\ndescription: quote a --- b end\ningested: true\n---\n# A\n")
assert fm.get("description") == "quote a --- b end", "mid-line --- must not truncate the value: %r" % fm
assert fm.get("ingested") == "true", "keys AFTER a mid-line --- must survive: %r" % fm
fm = wiki.parse_frontmatter("---\nname: B\n---\nbody\n\n---\n\nmore body\n")
assert fm == {"name": "B"}, "a body HR must not enter the frontmatter: %r" % fm
assert wiki.parse_frontmatter("no frontmatter here") == {}
assert wiki.parse_frontmatter("---\nname: C\nno closing delimiter") == {}, "unclosed block → empty"
print("ok 1: frontmatter delimiter is line-anchored; values with --- survive intact")

# =============================================================================================
# 2. Fold-write description cap — _finalize_ingest_pages truncates an over-cap description in place
#    (deterministic, JSON-quoted round-trip); an in-cap description is byte-for-byte untouched.
# =============================================================================================
w = _fresh("iwf2_")
long_desc = "An extremely detailed description of the topic " + "x" * 200
rel = "pages/topics/longdesc.md"
(w / rel).write_text("---\nname: L\ndescription: %s\ntype: topic\nslug: longdesc\nstatus: active\n---\n"
                     "# L\n\nprose\n\n## Sources\n- 2026-07-06 · aaaa1111 · n\n" % long_desc)
out = wiki._finalize_ingest_pages([rel], {"lint": {"desc_max_chars": 120}})
got = wiki.parse_frontmatter((w / rel).read_text())["description"]
assert len(got) <= 120, "fold-write must cap the description at the lint cap: %d chars" % len(got)
assert got.startswith("An extremely detailed"), "truncation must preserve the head: %r" % got[:40]
ok_rel = "pages/topics/short.md"
ok_text = ("---\nname: S\ndescription: fine.\ntype: topic\nslug: short\nstatus: active\n---\n"
           "# S\n\nprose\n\n## Sources\n- 2026-07-06 · aaaa1111 · n\n")
(w / ok_rel).write_text(ok_text)
wiki._finalize_ingest_pages([ok_rel], {"lint": {"desc_max_chars": 120}})
assert (w / ok_rel).read_text() == ok_text, "an in-cap page must be byte-for-byte untouched"
print("ok 2: over-cap description repaired at fold-write; in-cap page untouched")

# =============================================================================================
# 3. Companion-merge — a re-split APPENDS to the existing companion: previously-archived citations
#    survive, newly-moved ones join them (chronological), exact-duplicate lines dedupe.
# =============================================================================================
w = _fresh("iwf3_")
comp_rel = "pages/topics/big-sources.md"
(w / comp_rel).write_text(
    "---\nname: Big — earlier sources\ndescription: archive.\ntype: topic\nslug: big-sources\n"
    "status: active\n---\n# Big — earlier sources\n\nolder citations.\n\n## Sources\n"
    "- 2025-12-01 · 11111111 · PRECIOUS archived citation\n- 2026-01-01 · 22222222 · also archived\n")
src = ["## Sources"] + ["- 2026-02-%02d · 333333%02d · note %d" % (i + 1, i, i) for i in range(28)]
body = ["filler body line %d" % i for i in range(140)]
rel = "pages/topics/big.md"
(w / rel).write_text("\n".join(
    ["---", "name: Big", "description: d", "type: topic", "slug: big", "status: active", "---",
     "", "# Big", ""] + body + [""] + src + [""]))
out = wiki._finalize_ingest_pages([rel], {"lint": {"max_page_lines": 160}})
assert comp_rel in out, "the re-split must target the existing companion: %r" % out
comp_text = (w / comp_rel).read_text()
assert "PRECIOUS archived citation" in comp_text, "the merge must PRESERVE previously-archived citations"
assert "· 33333300 ·" in comp_text, "the merge must APPEND the newly-moved citations"
lines = comp_text.split("\n")
span = wiki._sources_block_span(lines)
bullets = lines[span[0]:span[1]]
assert len(bullets) == len(set(bullets)), "merged Sources must not contain duplicate lines"
dates = [b.split("·")[0].strip("- ").strip() for b in bullets]
assert dates == sorted(dates), "merged Sources must stay chronological: %r" % dates[:5]
assert (w / rel).read_text().count("\n") + 1 <= 160, "the main page must land under the cap"
print("ok 3: re-split merges into the existing companion — archive preserved, no dupes, chronological")

# =============================================================================================
# 4. Exact-path commits — git_commit_paths with explicit paths must leave an unrelated dirty page
#    uncommitted (the auto-ingest call site now passes exact paths, never the bare `pages` pathspec).
# =============================================================================================
w = _fresh("iwf4_", git=True)
tracked = w / "pages" / "topics" / "handedit.md"
tracked.write_text("---\nname: H\nslug: handedit\n---\n# H\n\noriginal\n")
subprocess.run(["git", "-C", str(w), "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", str(w), "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-q", "-m", "base"], capture_output=True)
tracked.write_text("---\nname: H\nslug: handedit\n---\n# H\n\nUSER HAND-EDIT IN FLIGHT\n")
batch = w / "pages" / "topics" / "batchpage.md"
batch.write_text("---\nname: B\nslug: batchpage\n---\n# B\n\nfold output\n")
r = wiki.git_commit_paths("ingest (auto): 1 sessions → batchpage", "pages/topics/batchpage.md")
assert r.returncode == 0, "the exact-path commit must succeed: %s" % (r.stderr,)
porcelain = subprocess.run(["git", "-C", str(w), "status", "--porcelain", "--", "pages"],
                           capture_output=True, text=True).stdout
assert "handedit.md" in porcelain, "the unrelated hand-edit must STAY uncommitted: %r" % porcelain
assert "batchpage.md" not in porcelain, "the batch page must be committed: %r" % porcelain
print("ok 4: exact-path commit lands the batch, leaves concurrent hand-edits alone")

print("PASS test_ingest_write_fixes")
