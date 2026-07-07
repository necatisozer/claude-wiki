# tests/test_init_fresh.py — rows 2/2b: fresh start straight into sync (sync/init design).
from sync_util import make_origin, run, sh, origin_main_sha
from pathlib import Path
import json, os, tempfile, subprocess

# happy: empty WIKI + empty bare → skeleton on main, pushed, armed; DEFAULT_CONFIG pinned (F8)
w = Path(tempfile.mkdtemp(prefix="wiki5_")) / "wiki"
o = make_origin()
r = run(["init", str(o), "--yes"], w)
assert r.returncode == 0, r.stdout + r.stderr
cfg = json.loads((w / "config.json").read_text())
assert cfg["ingest"]["cron"] and cfg["lint"]["cron"], "DEFAULT_CONFIG must carry both cron blocks"
assert sh(w, "git", "branch", "--show-current").stdout.strip() == "main"
assert origin_main_sha(o), "skeleton must be pushed"
assert '"enabled": true' in (w / "state" / "config.local.json").read_text()

# unreachable → rc 1, WIKI untouched (F1): not even created
w2 = Path(tempfile.mkdtemp(prefix="wiki5_")) / "wiki"
r = run(["init", "/nonexistent/nowhere.git", "--yes"], w2)
assert r.returncode == 1 and not (w2 / ".git").exists() and not (w2 / "config.json").exists()

# remote-create failure (PATH-faked gh) → tree untouched (R3)
w3 = Path(tempfile.mkdtemp(prefix="wiki5_")) / "wiki"
fake = Path(tempfile.mkdtemp(prefix="bin5_"))
(fake / "gh").write_text("#!/bin/sh\nif [ \"$1\" = repo ] && [ \"$2\" = view ]; then "
                         "echo 'GraphQL: Could not resolve to a Repository' >&2; exit 1; fi\n"
                         "echo 'gh create failed' >&2; exit 1\n")
os.chmod(fake / "gh", 0o755)
env = {**os.environ, "WIKI_HOME": str(w3), "PATH": str(fake) + os.pathsep + os.environ["PATH"]}
import sys
from sync_util import ENGINE
r = subprocess.run([sys.executable, ENGINE, "init", "someone/some-memory", "--yes"],
                   capture_output=True, text=True, env=env)
assert r.returncode == 1, r.stdout + r.stderr
assert not (w3 / ".git").exists() and not (w3 / "config.json").exists(), "create-first (R3): no local writes"

# F5: seed create-race dead-end. Router probe says "absent"; `gh repo create` tolerates
# "already exists" (a REAL race — the repo now genuinely has memory, ours from a prior crashed
# run or someone else's); the POST-CREATE re-probe must catch has_main and refuse BEFORE any
# skeleton write, not proceed into a doomed non-FF push that wedges the device with a fresh
# skeleton + origin already wired. Stateful fake gh: view #1 (routing probe) → not found;
# create → tolerated "already exists"; view #2 (the re-probe) → a REAL seeded bare's URL.
from sync_util import seed_origin
w3b = Path(tempfile.mkdtemp(prefix="wiki5_")) / "wiki"
real_bare = make_origin()
seed_origin(real_bare, {"journal/2026/07/x.md": "already has memory\n"})
fake3b = Path(tempfile.mkdtemp(prefix="bin5_"))
cnt3b = fake3b / "views"
(fake3b / "gh").write_text(
    "#!/bin/sh\n"
    'case "$1 $2" in\n'
    '  "repo view")\n'
    '    n=$(cat "%s" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "%s"\n'
    "    if [ \"$n\" -eq 1 ]; then\n"
    '      echo "GraphQL: Could not resolve to a Repository with the name '"'"'someone/x'"'"'." >&2\n'
    "      exit 1\n"
    "    fi\n"
    '    printf \'{"url": "%s"}\'; exit 0;;\n'
    '  "repo create") echo "GraphQL: Name already exists on this account" >&2; exit 1;;\n'
    '  "config get") echo https; exit 0;;\n'
    "esac\n"
    "exit 1\n" % (cnt3b, cnt3b, str(real_bare)[:-4]))       # url + ".git" reconstructs the bare's path
os.chmod(fake3b / "gh", 0o755)
env3b = {**os.environ, "WIKI_HOME": str(w3b), "PATH": str(fake3b) + os.pathsep + os.environ["PATH"]}
r = subprocess.run([sys.executable, ENGINE, "init", "someone/x", "--yes"],
                   capture_output=True, text=True, env=env3b)
assert r.returncode == 1, r.stdout + r.stderr
assert "already has memory" in r.stdout, "must reuse 2b'-style refusal wording: " + r.stdout
assert not (w3b / "config.json").exists(), "must refuse BEFORE any skeleton write: config.json"
assert not (w3b / ".gitignore").exists(), "must refuse BEFORE any skeleton write: .gitignore"
assert not (w3b / ".git").exists(), "must refuse BEFORE git init: .git"

# enable-last (g): probe succeeds (read is allowed) but the PUSH fails against a read-only
# bare → rc != 0 and the device is never armed
w5 = Path(tempfile.mkdtemp(prefix="wiki5_")) / "wiki"
o5 = make_origin()
ro = [o5] + [x for x in o5.rglob("*") if x.is_dir()]
for p in ro: os.chmod(p, 0o555)
r = run(["init", str(o5), "--yes"], w5)
for p in ro: os.chmod(p, 0o755)                       # restore perms so tempdir cleanup works
assert r.returncode != 0, "push against read-only origin must fail\n" + r.stdout + r.stderr
assert not (w5 / "state" / "config.local.json").exists(), "enable-last: must not arm"
# and the unreachable case above must not have armed either
assert not (w2 / "state" / "config.local.json").exists()

# seed-resume (row 2b): crashed seed = repo, no origin, no corpus → completes (F3)
w4 = Path(tempfile.mkdtemp(prefix="wiki5_"))
sh(w4, "git", "init", "-q", "-b", "main")
o4 = make_origin()
r = run(["init", str(o4), "--yes"], w4)
assert r.returncode == 0, r.stdout + r.stderr
assert origin_main_sha(o4) and (w4 / "config.json").exists()

# ambient-repo pin: git() must keep -C <WIKI> unconditionally — a missing WIKI must fail
# LOUDLY, never fall back to the engine's ambient CWD. Under Claude Code hooks the CWD is
# routinely inside the user's own project repo: a raw `wiki _push` there with a broken
# WIKI_HOME must not scan-and-push THAT repo's HEAD to its origin.
outer = Path(tempfile.mkdtemp(prefix="outer5_")) / "proj"
outer.mkdir()
sh(outer, "git", "init", "-q", "-b", "main")
sh(outer, "git", "config", "user.email", "t@t"); sh(outer, "git", "config", "user.name", "t")
(outer / "README.md").write_text("unrelated project\n")
sh(outer, "git", "add", "-A"); sh(outer, "git", "commit", "-q", "-m", "outer seed")
ob = make_origin()
sh(outer, "git", "remote", "add", "origin", str(ob))
missing = Path(tempfile.mkdtemp(prefix="wiki5_")) / "nonexistent" / "wiki"
env_out = {**os.environ, "WIKI_HOME": str(missing)}
r = subprocess.run([sys.executable, ENGINE, "_push"], capture_output=True, text=True,
                   env=env_out, cwd=outer)
assert r.returncode != 0, "missing WIKI must fail loudly, not run in the ambient CWD:\n" + r.stdout + r.stderr
assert origin_main_sha(ob) is None, "ambient-repo hazard: _push must never touch the CWD repo's origin"
r = subprocess.run([sys.executable, ENGINE, "sync", "--status"], capture_output=True, text=True,
                   env=env_out, cwd=outer)
assert "Traceback" not in r.stderr, "sync --status with a missing WIKI must not crash:\n" + r.stderr
print("ok test_init_fresh")
