# tests/test_scrub_hook.py — run: python3 tests/test_scrub_hook.py
from sync_util import *

ZERO = "0" * 40
FAKE = "ghp_" + "d" * 36

# hook installation (via probe) bakes paths + sets hooksPath
w, o = make_wiki(), make_origin()
wire_origin(w, o); enable_sync(w)
r = run(["_install-hook"], w)
assert r.returncode == 0, r.stderr
hook = w / ".githooks" / "pre-push"
assert hook.exists() and os.access(hook, os.X_OK)
assert sh(w, "git", "config", "core.hooksPath").stdout.strip() == ".githooks"
assert str(w) in hook.read_text(), "hook must bake WIKI_HOME"

# 1) new-ref push (remote sha = zeros) on a clean repo: hook must NOT die on zeros..sha
must(sh(w, "git", "push", "origin", "main"), "clean first push through hook")

# 2) clean NEW-BRANCH push exercises the hook's rev-list/full-history branch, then DELETION passes
must(sh(w, "git", "branch", "tmp"), "branch")
must(sh(w, "git", "push", "origin", "tmp"), "clean new-branch push through hook")
r = sh(w, "git", "push", "origin", ":tmp")             # DELETE the remote branch (local sha = zeros)
assert r.returncode == 0, "deletion (zero local sha) must be allowed: " + r.stderr

# 3) raw `git push` with a planted secret is blocked BY THE HOOK
commit_file(w, "journal/2026/07/oops.md", "x\n" + FAKE + "\n", "oops")
r = sh(w, "git", "push", "origin", "main")
assert r.returncode != 0, "hook must fail-close on a secret"
assert origin_main_sha(o) != sh(w, "git", "rev-parse", "HEAD").stdout.strip()

# 4) fail-closed: a syntactically valid but nonexistent "remote" sha makes the range rev-walk
# itself fail (bad revision) — the gate must treat that as a block, not silently scan nothing.
# Simpler equivalent of a true unfetched-remote-sha force push: probe _scrub-check directly.
valid_sha = sh(w, "git", "rev-parse", "HEAD").stdout.strip()
junk_sha = "a" * 40   # syntactically valid hex, but not a real object — the point is the rev-walk fails
r = run(["_scrub-check"], w,
        input="refs/heads/main %s refs/heads/main %s\n" % (valid_sha, junk_sha))
assert r.returncode != 0, "rev-walk failure must fail CLOSED, not silently pass: " + r.stdout + r.stderr
print("PASS test_scrub_hook")
