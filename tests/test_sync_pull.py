# tests/test_sync_pull.py — run: python3 tests/test_sync_pull.py
from sync_util import *

# wedge case: dirty tracked file → pull fails SOFT (flag set, no rebase left, proceeds)
w, o = make_wiki(), make_origin()
wire_origin(w, o); enable_sync(w)
run(["_push"], w)                                        # seed origin
import tempfile, subprocess as sp
clone = Path(tempfile.mkdtemp()) / "d"
sp.run(["git", "clone", "-q", str(o), str(clone)])
sh(clone, "git", "config", "user.email", "t@t"); sh(clone, "git", "config", "user.name", "t")
(clone / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nchanged remotely\n")
sh(clone, "git", "add", "-A"); sh(clone, "git", "commit", "-q", "-m", "r"); sh(clone, "git", "push", "-q", "origin", "main")
(w / "pages" / "topics" / "seed.md").write_text("locally dirty, uncommitted")   # dirty tree
r = run(["_pull-selftest"], w)
assert r.returncode == 0, r.stdout + r.stderr
assert "PULL-SOFT-FAIL" in r.stdout, "dirty tree must soft-fail"
assert (w / "state" / "pull_failed").exists()
assert not (w / ".git" / "rebase-merge").exists() and not (w / ".git" / "rebase-apply").exists(), \
    "no rebase may be left in progress"
# clean the tree → pull succeeds → flag clears → remote change landed
sh(w, "git", "checkout", "--", "pages/topics/seed.md")
r = run(["_pull-selftest"], w)
assert "PULL-OK" in r.stdout and not (w / "state" / "pull_failed").exists()
assert "changed remotely" in (w / "pages" / "topics" / "seed.md").read_text()

# surfacing: push_blocked + pull_failed appear in `wiki status` AND the digest
(w / "state" / "push_blocked").write_text("journal/x.md: [aws_key_id] AKIA…ZZ (len 20)")
(w / "state" / "pull_failed").write_text("test reason")
r = run(["status"], w)
assert "PUSH BLOCKED" in r.stdout.upper() and "PULL" in r.stdout.upper(), r.stdout
r = run(["digest"], w)
assert "push blocked" in r.stdout.lower(), "digest must surface the block: " + r.stdout[:300]
print("PASS test_sync_pull")
