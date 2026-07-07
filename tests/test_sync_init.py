# tests/test_sync_init.py — run: python3 tests/test_sync_init.py
from sync_util import *
import json

# ATTACH MODE (origin pre-wired → gh never called), starting on master to exercise the rename
w, o = make_wiki(branch="master"), make_origin()
wire_origin(w, o)
r = run(["sync", "--init", "--yes"], w)
assert r.returncode == 0, r.stdout + r.stderr
assert sh(w, "git", "branch", "--show-current").stdout.strip() == "main", "master must be renamed"
assert (w / ".githooks" / "pre-push").exists(), "hook installed"
cl = json.loads((w / "state" / "config.local.json").read_text())
assert cl["sync"]["enabled"] is True and cl["sync"]["branch"] == "main"
assert origin_main_sha(o), "first push must have landed"

# IDEMPOTENT: second run is a clean no-op
r = run(["sync", "--init", "--yes"], w)
assert r.returncode == 0, "re-run must succeed: " + r.stdout + r.stderr

# ENABLE-LAST: a failing first push must leave sync DISABLED
w2 = make_wiki(branch="master")
sh(w2, "git", "remote", "add", "origin", "/nonexistent/origin.git")
r = run(["sync", "--init", "--yes"], w2)
assert r.returncode != 0
cl2 = w2 / "state" / "config.local.json"
assert (not cl2.exists()) or not json.loads(cl2.read_text()).get("sync", {}).get("enabled"), \
    "enabled must NOT be armed when the first push fails"

# RESUMABLE: repair the remote → re-run --init completes and arms (spec §9 idempotent-resume)
o2 = make_origin()
sh(w2, "git", "remote", "set-url", "origin", str(o2))
# a user-set auto_push=false (e.g. from a prior partial/aborted init) must SURVIVE this re-run —
# --init must not clobber it back to the True default (regression: it used to write the whole object)
(w2 / "state" / "config.local.json").write_text(json.dumps({"sync": {"auto_push": False}}))
r = run(["sync", "--init", "--yes"], w2)
assert r.returncode == 0, "repaired re-run must complete: " + r.stdout + r.stderr
cl2_final = json.loads((w2 / "state" / "config.local.json").read_text())
assert cl2_final["sync"]["enabled"] is True
assert cl2_final["sync"]["auto_push"] is False, "pre-existing auto_push=false must survive --init re-run"
assert origin_main_sha(o2), "repaired re-run must push"

# SCAN GATE: a secret anywhere in history aborts init before anything is pushed
w3, o3 = make_wiki(), make_origin()
wire_origin(w3, o3)
commit_file(w3, "journal/2026/07/bad.md", ("xox" + "b-" + "9" * 12) + "\n", "bad")
commit_file(w3, "journal/2026/07/bad.md", "clean\n", "fix")
r = run(["sync", "--init", "--yes"], w3)
assert r.returncode != 0 and origin_main_sha(o3) is None, "init must abort with nothing pushed"

# plain `wiki sync` = pull → push (create divergence via a second clone, then sync)
import tempfile, subprocess as sp
clone = Path(tempfile.mkdtemp()) / "c"
sp.run(["git", "clone", "-q", str(o), str(clone)])
sh(clone, "git", "config", "user.email", "t@t"); sh(clone, "git", "config", "user.name", "t")
(clone / "pages" / "topics" / "remote.md").write_text("---\nname: R\n---\nr\n")
sh(clone, "git", "add", "-A"); sh(clone, "git", "commit", "-q", "-m", "remote change")
sh(clone, "git", "push", "-q", "origin", "main")
commit_file(w, "pages/topics/local.md", "---\nname: L\n---\nl\n", "local change")
r = run(["sync"], w)
assert r.returncode == 0, r.stdout + r.stderr
assert (w / "pages" / "topics" / "remote.md").exists(), "pull must land the remote page"
assert origin_main_sha(o) == sh(w, "git", "rev-parse", "HEAD").stdout.strip(), "push after rebase"

# --status renders
r = run(["sync", "--status"], w)
assert r.returncode == 0 and "origin" in r.stdout

# RENAME GUARD: a pre-existing 'main' branch must abort the master->main rename step, not let
# init silently proceed on a mismatched local branch (misattributed failure downstream)
w4, o4 = make_wiki(branch="master"), make_origin()
sh(w4, "git", "branch", "main")
wire_origin(w4, o4)
r = run(["sync", "--init", "--yes"], w4)
assert r.returncode != 0, "conflicting branch must abort init: " + r.stdout + r.stderr
cl4 = w4 / "state" / "config.local.json"
assert (not cl4.exists()) or not json.loads(cl4.read_text()).get("sync", {}).get("enabled"), \
    "enabled must NOT be armed when the rename fails"
assert "rename" in (r.stdout + r.stderr).lower(), \
    "error must name the rename step, not misattribute the cause: " + r.stdout + r.stderr

print("PASS test_sync_init")
