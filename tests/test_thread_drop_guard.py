# tests/test_thread_drop_guard.py — run: python3 tests/test_thread_drop_guard.py
#
# v0.1.20 — silent thread-drop hold. A live fold deleted 9 open `## Active threads` bullets from a
# project page with no session in the batch mentioning them; the diff cap happened not to trip, so
# accepting would have lost the follow-ups without a trace. A dropped bullet is ACCOUNTED FOR when a
# similar bullet survives on the new page or one of its distinctive tokens (ticket id, #PR, `code`)
# appears in text the batch newly added anywhere; more than ingest.max_dropped_threads (default 2)
# unaccounted drops on one page → hold, with a content-free reason.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; HOME + WIKI_HOME overridden BEFORE import — the live
# wiki and ~/.claude/settings*.json are never read or written. No credential-shaped literals.
import os, sys, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="tdg_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

os.environ["HOME"] = str(_mkdtemp("tdg_home_"))
os.environ["WIKI_HOME"] = str(_mkdtemp("tdg_import_"))
_loader = importlib.machinery.SourceFileLoader("wiki_engine_tdg", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_tdg", _loader))
_loader.exec_module(wiki)

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

THREADS = [
    "ECHO-1902 stays in TEST — QA blocked until the restyle entry ships.",
    "Run `pod install` to restore on-disk Pods.",
    "Restore the ad-hoc IPA to device for formal testing.",
    "Delete stale merged remote branches after force-push confirms.",
]
def page(threads, extra=""):
    return ("# P\n\n## Conventions & decisions\n- Uses Metro DI.\n%s\n## Active threads\n%s\n\n"
            "## Sources\n- 2026-07-30 · seed0001 · s\n" % (extra, "\n".join("- " + t for t in threads)))

HEAD = page(THREADS)
def drops(new, others_added=""):
    added = wiki._added_text(HEAD, new) + "\n" + others_added
    return wiki._unaccounted_thread_drops(HEAD, new, added)

check("unchanged page → 0", drops(HEAD) == 0)
check("all four silently dropped → 4", drops(page([])) == 4)
check("new page exempt", wiki._unaccounted_thread_drops(None, page([]), "") == 0)
check("reworded survivor accounted", drops(page([THREADS[0].replace("stays in TEST", "still in TEST")] + THREADS[1:])) == 0)
check("resolution recorded via ticket id", drops(page(THREADS[1:], "- ECHO-1902 verified and closed (2026-08-03).\n")) == 0)
check("moved to another page via code token", drops(page([t for t in THREADS if "pod install" not in t]),
                                                   others_added="- Ran `pod install` on the build box.") == 0)
check("token only in HEAD text doesn't count", drops(page(THREADS[1:])) == 1)
check("bullets outside Active threads ignored", wiki._section_bullets(HEAD) == THREADS)

# the hold gate: > cap unaccounted drops on one page → content-free reason
cfg = {"ingest": {"mode": "auto"}}
orig_git, orig_known = wiki.git, wiki._known_sid8s
class _G:
    def __init__(self, out): self.stdout, self.returncode = out, 0
wiki.git = lambda *a: _G(HEAD)
wiki._known_sid8s = lambda: {"seed0001"}
try:
    blk = lambda body: "=== FILE: pages/projects/p.md ===\n%s=== END ===\n" % body
    r3 = wiki._ingest_hold_reason(blk(page(THREADS[3:])), cfg)
    r4 = wiki._ingest_hold_reason(blk(page([])), cfg)
    r_ok = wiki._ingest_hold_reason(blk(page(THREADS[2:])), cfg)
    r_cfg = wiki._ingest_hold_reason(blk(page([])), {"ingest": {"mode": "auto", "max_dropped_threads": 5}})
finally:
    wiki.git, wiki._known_sid8s = orig_git, orig_known
check("3 drops > default cap 2 → hold", "3 active thread(s) dropped" in r3)
check("4 drops → hold", "4 active thread(s) dropped" in r4)
check("2 drops within cap → no thread hold", "active thread" not in r_ok)
check("config cap raises threshold", "active thread" not in r_cfg)
check("reason is content-free", "pod install" not in r4 and "ECHO-1902" not in r4)

sys.exit(1 if FAILS else 0)
