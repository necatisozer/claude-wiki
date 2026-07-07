# tests/test_init_publish_nogit.py — P2: corpus without .git → scan, adopt, publish (sync/init design).
from sync_util import ENGINE, make_origin, run, sh, must, origin_main_sha
from pathlib import Path
import os, sys, tempfile, subprocess

def bare_corpus():
    d = Path(tempfile.mkdtemp(prefix="wiki5_"))
    (d / "journal" / "2026" / "07").mkdir(parents=True)
    (d / "pages" / "topics").mkdir(parents=True)
    (d / "journal" / "2026" / "07" / "a.md").write_text("session notes\n")
    (d / "pages" / "topics" / "t.md").write_text("---\nname: T\n---\nbody\n")
    (d / "stray-root-note.md").write_text("stray but scannable\n")
    return d

# happy: adopt + publish + arm; adoption commit ⊆ walk; user-extra ignore honored (R7)
w = bare_corpus()
(w / ".gitignore").write_text("private-notes/\n")
(w / "private-notes").mkdir(); (w / "private-notes" / "p.md").write_text("kept out\n")
o = make_origin()
r = run(["init", str(o), "--yes"], w)
assert r.returncode == 0, r.stdout + r.stderr
tracked = sh(w, "git", "ls-files").stdout
assert "stray-root-note.md" in tracked and "journal/2026/07/a.md" in tracked
assert "private-notes/p.md" not in tracked, "user ignore entry must be honored, never -f forced"
gi = (w / ".gitignore").read_text()
assert "state/" in gi and ".DS_Store" in gi and "private-notes/" in gi, "required entries appended, user's kept"
assert '"enabled": true' in (w / "state" / "config.local.json").read_text()

# secret in untracked journal → abort BEFORE git init; no .gitignore written (F13)
w2 = bare_corpus()
fake = "AKIA" + "B" * 16                       # runtime-constructed, never a literal
(w2 / "journal" / "2026" / "07" / "bad.md").write_text("key=" + fake + "\n")
r = run(["init", str(make_origin()), "--yes"], w2)
assert r.returncode == 1, r.stdout + r.stderr
assert not (w2 / ".git").exists(), "must abort before git init"
assert not (w2 / ".gitignore").exists(), "scan-first: no writes on abort"
assert fake not in r.stdout, "output must be masked"

# binary in adoption set → refuse (stricter-than-push rule)
w3 = bare_corpus()
(w3 / "attachment.bin").write_bytes(b"\x00\x01binary")
r = run(["init", str(make_origin()), "--yes"], w3)
assert r.returncode == 1 and "binary" in (r.stdout + r.stderr).lower()
assert not (w3 / ".git").exists()

# --- fix-wave regressions (Task 3 review) -------------------------------------------------
from sync_util import origin_main_sha
import json

# scan ⊇ commit, empirically (R7): a secret in a USER-ignored path must still refuse — the
# ignored file would never reach the adoption commit, but it MUST reach the scan
w4 = bare_corpus()
(w4 / ".gitignore").write_text("private-notes/\n")
(w4 / "private-notes").mkdir()
(w4 / "private-notes" / "p.md").write_text("key=" + ("AKIA" + "C" * 16) + "\n")  # runtime-constructed
r = run(["init", str(make_origin()), "--yes"], w4)
assert r.returncode == 1, "user-ignored paths must still be scanned: " + r.stdout + r.stderr
assert not (w4 / ".git").exists(), "must abort before git init"
assert (w4 / ".gitignore").read_text() == "private-notes/\n", "abort must precede the gitignore patch"

# crashed-mid-adopt resume: .git exists (manual git init -b main) but ZERO commits, no origin →
# re-run completes end-to-end: adoption commit lands, first push reaches origin, sync arms
w5 = bare_corpus()
must(sh(w5, "git", "init", "-q", "-b", "main"), "manual git init")
o5 = make_origin()
r = run(["init", str(o5), "--yes"], w5)
assert r.returncode == 0, r.stdout + r.stderr
assert "adopt existing wiki corpus" in sh(w5, "git", "log", "--oneline").stdout
assert origin_main_sha(o5), "resumed adopt must complete the first push"
assert '"enabled": true' in (w5 / "state" / "config.local.json").read_text()

# _adopt_corpus rc must PROPAGATE: a failed adoption commit (sabotaged via a repo-local
# pre-commit hook — real subprocess run, no engine mocks) must abort the whole publish
# sequence; pre-fix the rc was discarded and (c)-(g) kept going (wired origin, wrote hook)
w6 = bare_corpus()
must(sh(w6, "git", "init", "-q", "-b", "main"), "manual git init")
(w6 / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
(w6 / ".git" / "hooks" / "pre-commit").chmod(0o755)
r = run(["init", str(make_origin()), "--yes"], w6)
assert r.returncode == 1, r.stdout + r.stderr
assert "adoption commit failed" in r.stdout
assert sh(w6, "git", "remote", "get-url", "origin").returncode != 0, \
    "publish must STOP after a failed adopt — origin must never be wired"
assert not (w6 / ".githooks" / "pre-push").exists(), "hook install must not run after a failed adopt"
cl6 = w6 / "state" / "config.local.json"
assert (not cl6.exists()) or not json.loads(cl6.read_text()).get("sync", {}).get("enabled"), \
    "sync must NOT be armed after a failed adopt"

# repo detection must be scoped to WIKI's OWN .git: a wiki nested inside an outer git repo
# (no .git of its own) must take the adoption path — own repo created, outer repo untouched
outer = Path(tempfile.mkdtemp(prefix="outer5_"))
must(sh(outer, "git", "init", "-q", "-b", "main"), "outer init")
sh(outer, "git", "config", "user.email", "t@t"); sh(outer, "git", "config", "user.name", "t")
(outer / "README.md").write_text("outer project\n")
sh(outer, "git", "add", "-A"); must(sh(outer, "git", "commit", "-q", "-m", "outer seed"), "outer seed")
w7 = outer / "inner" / "wiki"
(w7 / "journal" / "2026" / "07").mkdir(parents=True)
(w7 / "pages" / "topics").mkdir(parents=True)
(w7 / "journal" / "2026" / "07" / "a.md").write_text("session notes\n")
(w7 / "pages" / "topics" / "t.md").write_text("---\nname: T\n---\nbody\n")
o7 = make_origin()
r = run(["init", str(o7), "--yes"], w7)
assert r.returncode == 0, r.stdout + r.stderr
assert (w7 / ".git").exists(), "adoption must create the wiki's OWN repo, never use an ancestor's"
assert "adopt existing wiki corpus" in sh(w7, "git", "log", "--oneline").stdout
outer_log = sh(outer, "git", "log", "--oneline").stdout
assert "adopt" not in outer_log and len(outer_log.strip().splitlines()) == 1, \
    "outer repo must be untouched: " + outer_log
assert sh(outer, "git", "remote", "get-url", "origin").returncode != 0, "outer must not gain an origin"
assert sh(outer, "git", "config", "core.hooksPath").returncode != 0, "outer config must be untouched"

# F2 (severe variant of the above): the nested wiki's OWN .git is not merely absent but PRESENT
# and EMPTY (git discovery walks straight past it to the ancestor, same as an absent one — the
# .exists()-only guard fixed above misses this case). Invoked the realistic way — bare
# `wiki init --yes`, no target — routing must still land on adoption into WIKI's own fresh
# repo, never row 5 against the ancestor. Pre-fix this was the worst manifestation found: row 5
# taken directly (bypassing the router entirely, so it never even calls gh), the ancestor's
# REAL commit got scanned, its config gained core.hooksPath, and its HEAD was PUSHED to its own
# real origin under the engine's hardcoded "main" ref — empirically reproduced during this fix.
# A PATH-faked gh keeps the DEFAULT_MEMORY_REPO fallback probe hermetic (must never touch the
# real network or the user's actual private memory repo).
outer2 = Path(tempfile.mkdtemp(prefix="outer5_"))
must(sh(outer2, "git", "init", "-q", "-b", "main"), "outer2 init")
sh(outer2, "git", "config", "user.email", "t@t"); sh(outer2, "git", "config", "user.name", "t")
(outer2 / "README.md").write_text("outer project 2\n")
sh(outer2, "git", "add", "-A"); must(sh(outer2, "git", "commit", "-q", "-m", "outer2 seed"), "outer2 seed")
ancestor_origin2 = make_origin()
sh(outer2, "git", "remote", "add", "origin", str(ancestor_origin2))
outer2_log_before = sh(outer2, "git", "log", "--oneline").stdout

w8 = outer2 / "inner" / "wiki"
(w8 / "pages" / "topics").mkdir(parents=True)
(w8 / "journal" / "2026" / "07").mkdir(parents=True)
(w8 / "journal" / "2026" / "07" / "a.md").write_text("session notes\n")
(w8 / ".git").mkdir(parents=True)                         # EMPTY .git dir — present but invalid

fake8 = Path(tempfile.mkdtemp(prefix="wiki5_gh_"))
(fake8 / "gh").write_text(
    "#!/bin/sh\n"
    'case "$1 $2" in\n'
    '  "repo view") echo "GraphQL: Could not resolve to a Repository" >&2; exit 1;;\n'
    '  "repo create") echo "fake: unavailable in this test" >&2; exit 1;;\n'
    "esac\n"
    "exit 1\n")
(fake8 / "gh").chmod(0o755)
env8 = {**os.environ, "WIKI_HOME": str(w8), "PATH": str(fake8) + os.pathsep + os.environ["PATH"]}
r = subprocess.run([sys.executable, ENGINE, "init", "--yes"], capture_output=True, text=True, env=env8)

assert sh(outer2, "git", "config", "core.hooksPath").returncode != 0, \
    "ancestor config must NEVER gain core.hooksPath (F2): " + r.stdout + r.stderr
assert sh(outer2, "git", "log", "--oneline").stdout == outer2_log_before, \
    "ancestor repo history must be untouched"
assert sh(outer2, "git", "remote", "get-url", "origin").stdout.strip() == str(ancestor_origin2), \
    "ancestor's own origin config must be untouched"
assert origin_main_sha(ancestor_origin2) is None, \
    "ancestor's real origin must NEVER receive a push from this run"
print("ok test_init_publish_nogit")
