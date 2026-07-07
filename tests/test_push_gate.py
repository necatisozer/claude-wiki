# tests/test_push_gate.py — run: python3 tests/test_push_gate.py
from sync_util import *

FAKE = "AKIA" + "C" * 16          # runtime-constructed; NEVER a literal credential

# 1) clean first push (no branch on server → full-history mode) succeeds
w, o = make_wiki(), make_origin()
wire_origin(w, o); enable_sync(w, "main")
r = run(["_push"], w)
assert r.returncode == 0, r.stdout + r.stderr
head = sh(w, "git", "rev-parse", "HEAD").stdout.strip()
assert origin_main_sha(o) == head, "origin must have HEAD after clean push"

# 2) planted secret blocks; flag is masked; origin does not advance
commit_file(w, "journal/2026/07/leak.md", "note\n" + FAKE + "\n", "leak")
r = run(["_push"], w)
assert r.returncode == 1
flag = (w / "state" / "push_blocked").read_text()
assert "leak.md" in flag and FAKE not in flag, "flag must name file, MASKED"
assert origin_main_sha(o) == head, "origin must NOT advance on block"

# 3) redact-as-NEW-COMMIT still blocks (per-commit scan — the regression test)
commit_file(w, "journal/2026/07/leak.md", "note\nredacted\n", "fix")
r = run(["_push"], w)
assert r.returncode == 1, "endpoint-diff cancellation must NOT unblock"

# 4) history rewrite (squash the two bad commits away) unblocks + clears the flag
sh(w, "git", "reset", "--hard", head)
commit_file(w, "journal/2026/07/leak.md", "note\nredacted\n", "clean replay")
r = run(["_push"], w)
assert r.returncode == 0 and not (w / "state" / "push_blocked").exists()

# 5) non-fast-forward is benign: rc=2, NO push_blocked
import tempfile, subprocess as sp
clone = Path(tempfile.mkdtemp()) / "b"
sp.run(["git", "clone", "-q", str(o), str(clone)])
sh(clone, "git", "config", "user.email", "t@t"); sh(clone, "git", "config", "user.name", "t")
(clone / "other.md").write_text("x")
sh(clone, "git", "add", "-A"); sh(clone, "git", "commit", "-q", "-m", "b")
must(sh(clone, "git", "push", "-q", "origin", "main"), "case-5 seed push")
commit_file(w, "pages/topics/late.md", "---\nname: L\n---\nx\n", "late")
r = run(["_push"], w)
assert r.returncode == 2 and not (w / "state" / "push_blocked").exists(), "non-FF must be benign"

# 6) fallback parity: a NEVER-pushed repo (no branch on the server) → full-history mode →
#    a transient add-then-remove secret in history must block (a tree-only scan would pass it)
w2, o2 = make_wiki(), make_origin()
wire_origin(w2, o2); enable_sync(w2)
commit_file(w2, "journal/2026/07/t.md", "s\n" + ("sk-" + "ant-" + "y" * 24) + "\n", "transient")
commit_file(w2, "journal/2026/07/t.md", "s\nclean\n", "remove")
r = run(["_push"], w2)
assert r.returncode == 1, "transient secret in history must block a first push"

# 6b) TRUE stale-tracking-ref: pushed BEFORE (raw, no hook → bypasses the gate), then the remote is
#     deleted + recreated empty. The stale local origin/main would make a range scan look empty —
#     ls-remote (server truth) must force full-history mode and still block on the old transient.
import shutil
w4, o4 = make_wiki(), make_origin()
wire_origin(w4, o4); enable_sync(w4)
commit_file(w4, "journal/2026/07/t2.md", "s\n" + ("xox" + "p-" + "7" * 12) + "\n", "transient2")
commit_file(w4, "journal/2026/07/t2.md", "s\nclean\n", "remove2")
must(sh(w4, "git", "push", "-q", "origin", "main"), "6b raw seed push")   # tracking ref now exists
shutil.rmtree(o4)
sp.run(["git", "init", "-q", "--bare", "-b", "main", str(o4)])            # recreated EMPTY at same path
r = run(["_push"], w4)
assert r.returncode == 1, "stale tracking ref must not shrink the scan (server-truth detection)"

# 7) binary file under journal/ refuses
w3, o3 = make_wiki(), make_origin()
wire_origin(w3, o3); enable_sync(w3)
(w3 / "journal" / "2026" / "07" / "blob.md").write_bytes(bytes(range(256)) * 8)
sh(w3, "git", "add", "-A"); sh(w3, "git", "commit", "-q", "-m", "bin")
r = run(["_push"], w3)
assert r.returncode == 1, "binary under journal/ must refuse"

# 8) a secret in the commit MESSAGE (not the diff content) must also block — the `--format=%B` leg
w5, o5 = make_wiki(), make_origin()
wire_origin(w5, o5); enable_sync(w5)
msg_secret = "ghp_" + "e" * 36
(w5 / "innocent.md").write_text("nothing to see here\n")
sh(w5, "git", "add", "-A")
must(sh(w5, "git", "commit", "-q", "-m", "note: %s" % msg_secret), "case-8 seed commit")
r = run(["_push"], w5)
assert r.returncode == 1, "secret in commit MESSAGE must block push (the --format=%B leg)"
print("PASS test_push_gate")
