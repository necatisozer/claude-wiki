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

TRANSCRIPT = "transcripts/aaaa1111-2222-3333-4444-555566667777.jsonl.gz"

def other_device(origin, page_body=None, log_line=None, files=None):
    """A second clone pushes conflicting content: a rewrite of the SAME seed page, its own op-log
    line (like every real record/ingest commit), and/or arbitrary files (rel → str|bytes)."""
    c = Path(tempfile.mkdtemp()) / "d2"
    must(sh(Path(tempfile.gettempdir()), "git", "clone", "-q", str(origin), str(c)))
    sh(c, "git", "config", "user.email", "t@t"); sh(c, "git", "config", "user.name", "t")
    if page_body is not None:
        (c / "pages" / "topics" / "seed.md").write_text(page_body)
    if log_line:
        with (c / "log.md").open("a") as f:
            f.write(log_line)
    for rel, content in (files or {}).items():
        p = c / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content) if isinstance(content, bytes) else p.write_text(content)
    sh(c, "git", "add", "-A"); must(sh(c, "git", "commit", "-q", "-m", "device-2 fold"))
    must(sh(c, "git", "push", "-q", "origin", "main"))

# ============================================================================================
# 1. DERIVED-ONLY CONFLICT → auto-heals: remote page wins, local journal survives un-ingested.
#    PRODUCTION-SHAPED commits: every real record/ingest commit also carries `log.md` (op-log)
#    and record commits carry `transcripts/<sid>.jsonl.gz` — the heal must treat those as
#    re-appliable, not as authored files (a bare journal+pages fixture would pass with a heal
#    that aborts on every real conflict).
# ============================================================================================
w, o = make_wiki(), make_origin()
(w / "log.md").write_text("# Operations log\n\n- 2026-07-19T00:00:00Z · record · shared line\n")
sh(w, "git", "add", "-A"); sh(w, "git", "commit", "-q", "-m", "log seed")
wire_origin(w, o); enable_sync(w)
run(["_push"], w)                                        # seed origin from device 1

other_device(o, "---\nname: Seed\n---\nDEVICE-2 fold of the page\n",
             log_line="- 2026-07-20T09:00:00Z · ingest · device-2 fold\n")

# device 1 folds the same page AND records a new journal entry + transcript + op-log line — the
# exact file set _record_sync_commit_push / _ingest_auto_batch attach to their commits
(w / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nDEVICE-1 fold of the page\n")
(w / JOURNAL).parent.mkdir(parents=True, exist_ok=True)
(w / JOURNAL).write_text(entry(ingested="true"))
(w / "transcripts").mkdir()
GZ_BYTES = b"\x1f\x8b\x08\x00binary-ish\x00payload"      # gzip magic — content must survive byte-exact
(w / TRANSCRIPT).write_bytes(GZ_BYTES)
with (w / "log.md").open("a") as f:
    f.write("- 2026-07-20T10:00:00Z · record · device-1 local work\n")
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
# the synced transcript copy survived BYTE-EXACT (it is binary gzip — text round-trips corrupt it)
assert (w / TRANSCRIPT).read_bytes() == GZ_BYTES, "transcript copy must be re-applied byte-exact"
# the op-log holds BOTH devices' lines (remote's version + this device's re-appended local lines)
merged_log = (w / "log.md").read_text()
assert "device-2 fold" in merged_log and "device-1 local work" in merged_log, \
    "op-log must merge, not lose either device's lines:\n" + merged_log
# nothing was made unreachable
assert sh(w, "git", "rev-parse", "--verify", "sync-preconflict").returncode == 0, \
    "pre-reset HEAD must be pinned to a recovery branch"
# the heal's own lost-pages op-log line must ride IN the heal commit — a dirty tracked log.md
# left behind would wedge every subsequent pull on the clean-tree guard
assert sh(w, "git", "status", "--porcelain", "--untracked-files=no").stdout.strip() == "", \
    "the heal must leave a clean tracked tree (dirty log.md wedges the next pull):\n" + \
    sh(w, "git", "status", "--porcelain").stdout
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

# ============================================================================================
# 3. UNCOMMITTED work on disk (a held ingest batch's page edit, an in-progress hand-edit) must
#    ABORT the heal: `reset --hard` would destroy it and no recovery branch holds uncommitted
#    content. Soft-fail + flag, uncommitted content untouched.
# ============================================================================================
w3, o3 = make_wiki(), make_origin()
wire_origin(w3, o3); enable_sync(w3)
run(["_push"], w3)
other_device(o3, "---\nname: Seed\n---\nDEVICE-2 fold once more\n")

# a committed derived-only change (heal-eligible) PLUS an uncommitted tracked edit on top
(w3 / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nDEVICE-1 fold once more\n")
sh(w3, "git", "add", "-A"); must(sh(w3, "git", "commit", "-q", "-m", "device-1 fold"))
(w3 / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nUNCOMMITTED hand-edit\n")

r = run(["_pull-selftest"], w3)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-SOFT-FAIL" in r.stdout, \
    "uncommitted work must abort the heal (reset --hard would destroy it):\n" + r.stdout
assert "UNCOMMITTED hand-edit" in (w3 / "pages" / "topics" / "seed.md").read_text(), \
    "uncommitted content must never be destroyed by the heal"
assert (w3 / "state" / "pull_failed").exists(), "aborted heal must set the soft-fail flag"
print("ok 3: uncommitted working-tree changes abort the heal untouched")

# ============================================================================================
# 4. A committed LOCAL DELETION of a transcript (a purge, e.g. after a scrub finding) must be
#    RE-APPLIED by the heal — never resurrected from the remote's copy.
# ============================================================================================
w4, o4 = make_wiki(), make_origin()
(w4 / "transcripts").mkdir()
(w4 / TRANSCRIPT).write_bytes(b"\x1f\x8b\x08\x00sensitive-payload")
sh(w4, "git", "add", "-A"); must(sh(w4, "git", "commit", "-q", "-m", "seed transcript"))
wire_origin(w4, o4); enable_sync(w4)
run(["_push"], w4)                                       # origin now HOLDS the transcript
other_device(o4, "---\nname: Seed\n---\nDEVICE-2 fold\n")

# device 1 PURGES the transcript and folds the same page (derived conflict)
(w4 / TRANSCRIPT).unlink()
(w4 / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nDEVICE-1 fold\n")
sh(w4, "git", "add", "-A"); must(sh(w4, "git", "commit", "-q", "-m", "purge transcript + fold"))

r = run(["_pull-selftest"], w4)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-OK" in r.stdout, "a local purge must not block the heal:\n" + r.stdout
assert not (w4 / TRANSCRIPT).exists(), \
    "a committed local deletion must be RE-APPLIED, never resurrected from the remote"
assert sh(w4, "git", "ls-files", "--error-unmatch", TRANSCRIPT).returncode != 0, \
    "the re-applied deletion must be committed (file must not be tracked)"
print("ok 4: a committed transcript purge survives the heal (never resurrected)")

# ============================================================================================
# 5. BOTH devices changed the SAME transcript file (e.g. a remote re-redaction vs a stale local
#    copy) → fail closed: blindly re-applying local bytes would revert the remote's scrub.
# ============================================================================================
w5, o5 = make_wiki(), make_origin()
(w5 / "transcripts").mkdir()
(w5 / TRANSCRIPT).write_bytes(b"\x1f\x8b\x08\x00v1-with-missed-secret")
sh(w5, "git", "add", "-A"); must(sh(w5, "git", "commit", "-q", "-m", "seed transcript"))
wire_origin(w5, o5); enable_sync(w5)
run(["_push"], w5)

# device 2 RE-REDACTS the same transcript (rewrites its bytes) and pushes
other_device(o5, files={TRANSCRIPT: b"\x1f\x8b\x08\x00v2-scrubbed"})

# device 1 also rewrites its (stale, unredacted) copy locally + commits
(w5 / TRANSCRIPT).write_bytes(b"\x1f\x8b\x08\x00v1b-still-unredacted")
sh(w5, "git", "add", "-A"); must(sh(w5, "git", "commit", "-q", "-m", "local rewrite"))

r = run(["_pull-selftest"], w5)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-SOFT-FAIL" in r.stdout, \
    "a both-sides transcript edit must fail closed (heal would revert the remote scrub):\n" + r.stdout
assert b"v1b-still-unredacted" in (w5 / TRANSCRIPT).read_bytes(), \
    "fail-closed must leave the local tree untouched"
print("ok 5: both-devices transcript edit fails closed (remote re-redaction never reverted)")

# ============================================================================================
# 6. A LOCAL log.md REDACTION (a committed line removal) must fail closed — the append-only
#    merge would otherwise keep the remote's copy of the removed line and report success.
# ============================================================================================
w6, o6 = make_wiki(), make_origin()
(w6 / "log.md").write_text("# Operations log\n\n- 2026-07-19T00:00:00Z · record · SENSITIVE line\n"
                           "- 2026-07-19T01:00:00Z · record · benign line\n")
sh(w6, "git", "add", "-A"); sh(w6, "git", "commit", "-q", "-m", "log seed")
wire_origin(w6, o6); enable_sync(w6)
run(["_push"], w6)                                       # origin holds the SENSITIVE line
other_device(o6, "---\nname: Seed\n---\nDEVICE-2 fold\n")

# device 1 REDACTS the sensitive op-log line + folds the same page, commits
(w6 / "log.md").write_text("# Operations log\n\n- 2026-07-19T01:00:00Z · record · benign line\n")
(w6 / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nDEVICE-1 fold\n")
sh(w6, "git", "add", "-A"); must(sh(w6, "git", "commit", "-q", "-m", "redact log + fold"))

r = run(["_pull-selftest"], w6)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-SOFT-FAIL" in r.stdout, \
    "a local log.md line removal must fail closed (merge would revert the redaction):\n" + r.stdout
assert "SENSITIVE" not in (w6 / "log.md").read_text(), \
    "fail-closed must leave the local redacted log.md untouched"
print("ok 6: a committed log.md redaction fails closed (never reverted by the merge)")

print("PASS test_sync_derived_conflict")
