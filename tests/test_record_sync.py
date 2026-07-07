# tests/test_record_sync.py — run: python3 tests/test_record_sync.py
from sync_util import *
import time

# probe pass 1: rename cases (1+2) — the detached push must land BEFORE we break anything
w, o = make_wiki(), make_origin()
wire_origin(w, o); enable_sync(w)
r = run(["_sync-selftest"], w)
print(r.stdout, r.stderr)
assert r.returncode == 0
assert "CASE1-OK" in r.stdout, "untracked old_page must not break the commit"
assert "CASE2-OK" in r.stdout, "tracked old_page deletion must be staged (pull --rebase works after)"
# poll for the EXACT post-case-2 sha (stronger than 'origin has anything')
want = sh(w, "git", "rev-parse", "HEAD").stdout.strip()
deadline = time.time() + 20
while time.time() < deadline and origin_main_sha(o) != want:
    time.sleep(0.5)
assert origin_main_sha(o) == want, "record's detached push must reach origin (exact sha)"

# probe pass 2: failure isolation — ONLY NOW break the remote (no race with the detached push)
r = run(["_sync-selftest", "--case3"], w)
assert r.returncode == 0 and "CASE3-OK" in r.stdout, "bad remote must be swallowed"

# sync OFF → probe makes NO commits (byte-identical no-op)
w2 = make_wiki()
base = sh(w2, "git", "rev-parse", "HEAD").stdout.strip()
r = run(["_sync-selftest", "--off"], w2)
assert r.returncode == 0 and "OFF-OK" in r.stdout
assert sh(w2, "git", "rev-parse", "HEAD").stdout.strip() == base, "sync-off must not commit"

# the inserted CALL must use slugify(title), never a bare `slug` (NameError landmine).
# (the def's parameter being NAMED slug is fine — only the cmd_record call site matters, so the
# check below excludes the `def` line itself: a blind whole-file substring match would always
# collide with `def _record_sync_commit_push(old_page, page, slug, sid):` regardless of whether
# the call site is correct.)
engine_src = Path(ENGINE).read_text()
assert "_record_sync_commit_push(old_page, page, slugify(title), sid)" in engine_src, \
    "record insertion must pass slugify(title)"
bad_call = any("_record_sync_commit_push(old_page, page, slug, sid)" in ln
               and not ln.lstrip().startswith("def ")
               for ln in engine_src.splitlines())
assert not bad_call, "a bare `slug` arg would NameError in cmd_record"
print("PASS test_record_sync")
