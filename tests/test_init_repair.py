# tests/test_init_repair.py — row 0 validate/repair (F5, R4).
from sync_util import make_wiki, make_origin, wire_origin, run, sh, must
from pathlib import Path
import tempfile
w = make_wiki(); o = make_origin(); wire_origin(w, o)
assert run(["init", "--yes"], w).returncode == 0
hook = w / ".githooks" / "pre-push"
hook.unlink(); assert not hook.exists()
r = run(["init"], w)                                   # armed + hook deleted → reinstall, rc 0
assert r.returncode == 0 and hook.exists(), "row 0 must reinstall the hook\n" + r.stdout + r.stderr
sh(w, "git", "remote", "remove", "origin")             # armed + origin gone → rc 1, named
r = run(["init"], w); assert r.returncode == 1 and "origin" in r.stdout, r.stdout + r.stderr
wire_origin(w, o)
for t in sh(w, "git", "ls-files").stdout.splitlines(): (w / t).unlink()
r = run(["init"], w)                                   # armed + emptied worktree → rc 1 (R4)
assert r.returncode == 1, "armed+emptied must not report healthy\n" + r.stdout + r.stderr

# F1: armed row 0 with WIKI's own .git GONE, nested inside an ancestor repo that has its OWN
# origin remote and no core.hooksPath. Pre-fix, `git rev-parse --git-dir` walks UP to the
# ancestor: the origin check reads the ANCESTOR's origin, and (hook file missing under WIKI)
# _write_prepush_hook() writes `git config core.hooksPath .githooks` straight into the
# ANCESTOR's config, then prints "healthy" rc 0 — a live mutation of the user's own project repo.
outer = Path(tempfile.mkdtemp(prefix="f1outer_"))
must(sh(outer, "git", "init", "-q", "-b", "main"), "outer init")
sh(outer, "git", "config", "user.email", "t@t"); sh(outer, "git", "config", "user.name", "t")
(outer / "README.md").write_text("outer project\n")
sh(outer, "git", "add", "-A"); must(sh(outer, "git", "commit", "-q", "-m", "outer seed"), "outer seed")
sh(outer, "git", "remote", "add", "origin", str(make_origin()))
outer_log_before = sh(outer, "git", "log", "--oneline").stdout

w10 = outer / "inner" / "wiki"
(w10 / "state").mkdir(parents=True); (w10 / "logs").mkdir()
(w10 / "pages" / "topics").mkdir(parents=True); (w10 / "journal" / "2026" / "07").mkdir(parents=True)
(w10 / "config.json").write_text('{"enabled": true}')
(w10 / "state" / "config.local.json").write_text(
    '{"sync": {"enabled": true, "remote": "origin", "branch": "main", "auto_push": true}}')
# NOTE: w10 has NO .git of its own at all — "armed but .git gone" scenario

r = run(["init"], w10)
assert r.returncode == 1 and "BROKEN" in r.stdout, \
    "nested armed-but-gitless must report BROKEN, never ancestor-healthy: " + r.stdout + r.stderr
assert sh(outer, "git", "config", "core.hooksPath").returncode != 0, \
    "ancestor config must NEVER gain core.hooksPath (F1)"
assert sh(outer, "git", "log", "--oneline").stdout == outer_log_before, \
    "ancestor repo history must be untouched"
print("ok test_init_repair")
