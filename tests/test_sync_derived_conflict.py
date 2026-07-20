# tests/test_sync_derived_conflict.py — v0.1.13 multi-device derived-file conflict auto-heal.
# Two devices fold the same day: both rewrite pages/ (+ index.md), so the second to pull hits a rebase
# conflict. Journal is the source of truth and pages are derived, so the conflict resolves itself:
# remote pages win, local journal entries are re-applied UN-ingested for the next ingest to re-fold.
from sync_util import *
import subprocess as sp, tempfile

JOURNAL = "journal/2026/07/2026-07-20__local-work__aaaa1111.md"

def entry(ingested="true"):
    return ("---\nname: Local work\ndescription: d\ntype: session\n"
            "sessionId: aaaa1111-2222-3333-4444-555566667777\n"
            "project: p\ndate: 2026-07-20\nended: 2026-07-20T10:00:00Z\n"
            "ingested: %s\n---\n\n# Local work\n\nlocal-only knowledge worth keeping\n" % ingested)

def other_device(origin, page_body):
    """A second clone pushes a conflicting rewrite of the SAME page."""
    c = Path(tempfile.mkdtemp()) / "d2"
    must(sh(Path(tempfile.gettempdir()), "git", "clone", "-q", str(origin), str(c)))
    sh(c, "git", "config", "user.email", "t@t"); sh(c, "git", "config", "user.name", "t")
    (c / "pages" / "topics" / "seed.md").write_text(page_body)
    sh(c, "git", "add", "-A"); must(sh(c, "git", "commit", "-q", "-m", "device-2 fold"))
    must(sh(c, "git", "push", "-q", "origin", "main"))

# ============================================================================================
# 1. DERIVED-ONLY CONFLICT → auto-heals: remote page wins, local journal survives un-ingested.
# ============================================================================================
w, o = make_wiki(), make_origin()
wire_origin(w, o); enable_sync(w)
run(["_push"], w)                                        # seed origin from device 1

other_device(o, "---\nname: Seed\n---\nDEVICE-2 fold of the page\n")

# device 1 folds the same page AND records a new journal entry, then commits locally
(w / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nDEVICE-1 fold of the page\n")
(w / JOURNAL).parent.mkdir(parents=True, exist_ok=True)
(w / JOURNAL).write_text(entry(ingested="true"))
sh(w, "git", "add", "-A"); must(sh(w, "git", "commit", "-q", "-m", "device-1 fold"))

r = run(["_pull-selftest"], w)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-OK" in r.stdout, "derived-only conflict must heal, not soft-fail:\n" + r.stdout
assert not (w / "state" / "pull_failed").exists(), "healed pull must leave no failure flag"

# remote's derived page won...
assert "DEVICE-2" in (w / "pages" / "topics" / "seed.md").read_text(), \
    "remote pages must win a derived conflict"
# ...and the local journal entry survived, flipped to un-ingested so the next ingest re-folds it
assert (w / JOURNAL).exists(), "local journal entry must be re-applied, never discarded"
body = (w / JOURNAL).read_text()
assert "local-only knowledge worth keeping" in body, "journal content must be preserved verbatim"
assert "ingested: false" in body, "re-applied entry must be marked un-ingested for re-fold:\n" + body
# nothing was made unreachable
assert sh(w, "git", "rev-parse", "--verify", "sync-preconflict").returncode == 0, \
    "pre-reset HEAD must be pinned to a recovery branch"
print("ok 1: derived-only conflict auto-heals (remote pages win, local journal re-applied un-ingested)")

# ============================================================================================
# 2. FAIL CLOSED — an AUTHORED local change in the conflict must NOT be auto-discarded.
# ============================================================================================
w2, o2 = make_wiki(), make_origin()
wire_origin(w2, o2); enable_sync(w2)
run(["_push"], w2)
other_device(o2, "---\nname: Seed\n---\nDEVICE-2 fold again\n")

(w2 / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nDEVICE-1 fold again\n")
(w2 / "config.json").write_text('{"enabled": true, "ingest": {"cron": "30 21 * * *"}}')  # authored!
sh(w2, "git", "add", "-A"); must(sh(w2, "git", "commit", "-q", "-m", "device-1 fold + hand-edited config"))

r = run(["_pull-selftest"], w2)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-SOFT-FAIL" in r.stdout, \
    "an authored file in the conflict must fall back to flag-and-proceed:\n" + r.stdout
assert (w2 / "state" / "pull_failed").exists(), "soft-fail must set the flag"
assert "30 21" in (w2 / "config.json").read_text(), "hand-edited config must never be auto-discarded"
assert not (w2 / ".git" / "rebase-merge").exists() and not (w2 / ".git" / "rebase-apply").exists(), \
    "no rebase may be left in progress"
print("ok 2: an authored local change fails closed (config preserved, flag set)")

print("PASS test_sync_derived_conflict")
