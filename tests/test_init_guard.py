# tests/test_init_guard.py — routing refusals + alias/back-compat (spec rows 0/2b'/4/5).
from sync_util import make_wiki, make_origin, seed_origin, wire_origin, run, sh, must
from pathlib import Path
import subprocess, tempfile

# row 4: corpus + no origin + TARGET has_main → refuse, no mutation
w = make_wiki(); sh(w, "git", "remote", "remove", "origin")
full = make_origin(); seed_origin(full, {"journal/2026/07/a.md": "j\n"})
r = run(["init", str(full), "--yes"], w)
assert r.returncode == 1 and "remote already has memory" in r.stdout, r.stdout + r.stderr
assert sh(w, "git", "remote", "get-url", "origin").returncode != 0, "row 4 must not wire origin"

# row 2b': seeded-empty repo (no corpus) + has_main → refuse (R2)
e = Path(tempfile.mkdtemp(prefix="wiki5_"))
sh(e, "git", "init", "-q", "-b", "main")
r = run(["init", str(full), "--yes"], e)
assert r.returncode == 1 and "part-initialized empty wiki" in r.stdout, r.stdout + r.stderr

# unreachable → abort, byte-unchanged (F1)
w2 = make_wiki(); sh(w2, "git", "remote", "remove", "origin")
before = sh(w2, "git", "status", "--porcelain").stdout
r = run(["init", "/nonexistent/nowhere.git", "--yes"], w2)
assert r.returncode == 1 and "remote unreachable" in r.stdout, r.stdout + r.stderr
assert sh(w2, "git", "status", "--porcelain").stdout == before

# row 5 ≡ (a)-(g): repo + origin(empty bare) + --yes → pushed + armed; bare re-run rc 0 (row 0)
w3 = make_wiki(); o3 = make_origin(); wire_origin(w3, o3)
r = run(["init", "--yes"], w3); assert r.returncode == 0, r.stdout + r.stderr
assert (w3 / "state" / "config.local.json").exists() and "true" in (w3 / "state" / "config.local.json").read_text().lower()
r = run(["init"], w3); assert r.returncode == 0, "armed re-run must be rc 0 (row 0)\n" + r.stdout + r.stderr

# F4: row-5 mixed guard's `git ls-files` must use -c core.quotePath=false (its sibling
# _worktree_emptied already does) — a tracked non-ASCII filename otherwise lists C-quoted
# (e.g. "caf\303\251.md"), never matches (WIKI / t).exists() for the real path, and gets
# spuriously counted as "missing" → permanent false "worktree damaged" refusal.
wq = make_wiki()
(wq / "journal" / "2026" / "07" / "café.md").write_text("session notes\n")
sh(wq, "git", "add", "-A")
sh(wq, "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add café")
oq = make_origin(); wire_origin(wq, oq)
r = run(["init", "--yes"], wq)
assert r.returncode == 0 and "worktree damaged" not in r.stdout, \
    "non-ASCII tracked filename must not trip the mixed guard: " + r.stdout + r.stderr

# row 0 explicit mismatching TARGET → rc 1; F2: bare init must NOT compare origin to the default
r = run(["init", "someone/other-repo"], w3)
assert r.returncode == 1 and "refusing different TARGET" in r.stdout, r.stdout + r.stderr

# row 5 (unarmed) explicit mismatching TARGET → rc 1, not armed
w5 = make_wiki(); o5 = make_origin(); wire_origin(w5, o5)
r = run(["init", "/some/other/remote.git", "--yes"], w5)
assert r.returncode == 1 and "refusing different TARGET" in r.stdout, r.stdout + r.stderr
assert not (w5 / "state" / "config.local.json").exists()

# alias: `sync --init --yes` forwards (fresh wiki + empty origin)
w4 = make_wiki(); o4 = make_origin(); wire_origin(w4, o4)
r = run(["sync", "--init", "--yes"], w4); assert r.returncode == 0, r.stdout + r.stderr

# (d)-leg guard: gh `repo view` answering {} must abort "cannot resolve remote url", NOT build
# ".git" from the empty url field and wire a bogus self-referential origin (which _push_gated
# would then "succeed" against as a no-op and arm sync). The fake gh is STATEFUL: view #1 (the
# routing probe in _remote_state) resolves to a real empty bare so cmd_init reaches row 3's
# _init_publish; view #2 (the (d) leg's own re-resolution) returns {}. An always-{} fake never
# reaches (d): the probe itself fails closed first (that variant is the next case below).
import os, sys
from sync_util import ENGINE

def run_gh(args, wiki, ghdir):
    env = {**os.environ, "WIKI_HOME": str(wiki),
           "PATH": "%s%s%s" % (ghdir, os.pathsep, os.environ["PATH"])}
    return subprocess.run([sys.executable, ENGINE] + args, capture_output=True, text=True, env=env)

w6 = make_wiki(); sh(w6, "git", "remote", "remove", "origin")
o6 = make_origin()
fake = Path(tempfile.mkdtemp(prefix="wiki5_gh_"))
cnt = fake / "views"
(fake / "gh").write_text(
    "#!/bin/sh\n"
    'case "$1 $2" in\n'
    '  "repo view")\n'
    '    n=$(cat "%s" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "%s"\n'
    "    if [ \"$n\" -eq 1 ]; then printf '{\"url\": \"%s\"}'; else printf '{}'; fi; exit 0;;\n"
    '  "repo create") exit 0;;\n'
    '  "config get") echo https; exit 0;;\n'
    "esac\n"
    "exit 1\n" % (cnt, cnt, str(o6)[:-4]))          # url + ".git" reconstructs the bare's path
(fake / "gh").chmod(0o755)
r = run_gh(["init", "someone/x", "--yes"], w6, fake)
assert r.returncode == 1 and "cannot resolve remote url" in r.stdout, r.stdout + r.stderr
assert sh(w6, "git", "remote", "get-url", "origin").returncode != 0, \
    "empty gh url must not wire a bogus origin"

# _remote_state guard (same bug's sibling): gh view {} at the ROUTING PROBE must fail closed as
# unreachable ("gh returned no url"), not build ".git" — which ls-remote resolves to the wiki's
# OWN repo (has_main), misrouting a fresh publish to the row-4 refusal.
w7 = make_wiki(); sh(w7, "git", "remote", "remove", "origin")
fake2 = Path(tempfile.mkdtemp(prefix="wiki5_gh_"))
(fake2 / "gh").write_text(
    "#!/bin/sh\n"
    'case "$1 $2" in\n'
    "  \"repo view\") printf '{}'; exit 0;;\n"
    '  "repo create") exit 0;;\n'
    '  "config get") echo https; exit 0;;\n'
    "esac\n"
    "exit 1\n")
(fake2 / "gh").chmod(0o755)
r = run_gh(["init", "someone/y", "--yes"], w7, fake2)
assert r.returncode == 1 and "gh returned no url" in r.stdout, r.stdout + r.stderr
assert sh(w7, "git", "remote", "get-url", "origin").returncode != 0, "no origin on probe failure"

# F6: _init_publish's (d)-leg gh calls run while holding all four job locks — a hung gh must
# not starve detached records forever. config-get carries the shortest bound (timeout=10); a
# fake gh that hangs there must return within it (not indefinitely) with a named failure, and
# the locks must release (proven by an immediate follow-up not blocking).
import time
w8 = make_wiki(); sh(w8, "git", "remote", "remove", "origin")
fake3 = Path(tempfile.mkdtemp(prefix="wiki5_gh_"))
(fake3 / "gh").write_text(
    "#!/bin/sh\n"
    'case "$1 $2" in\n'
    '  "repo view") echo "GraphQL: Could not resolve to a Repository" >&2; exit 1;;\n'
    '  "repo create") exit 0;;\n'
    '  "config get") sleep 12; echo https; exit 0;;\n'
    "esac\n"
    "exit 1\n")
(fake3 / "gh").chmod(0o755)
t0 = time.time()
r = run_gh(["init", "someone/hangtest", "--yes"], w8, fake3)
elapsed = time.time() - t0
assert elapsed < 20, "must return near the 10s config-get bound, not hang: %.1fs" % elapsed
assert r.returncode == 1 and "timed out" in r.stdout, \
    "hung gh config-get must fail closed with a named timeout: " + r.stdout + r.stderr
t1 = time.time()
r2 = run(["init"], w8)
assert time.time() - t1 < 10, "locks must release after the timeout — follow-up must not block"

print("ok test_init_guard")
