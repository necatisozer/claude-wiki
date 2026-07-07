# tests/test_init_state.py — state helpers: normalization, probes, signals.
import subprocess, sys
from pathlib import Path
from sync_util import ENGINE, make_wiki, make_origin, seed_origin, sh

# NOTE: probe() and its call sites use eval()/repr() to shuttle Python literals out of a
# subprocess. This is test-only code: the `code` snippets are string literals written below
# (not external input), and the eval()'d stdout is the repr() of objects this same test caused
# the subprocess to print — never attacker-controlled or network-sourced data.
def probe(wiki, code):
    """Run a python snippet inside the engine module with WIKI_HOME=wiki, print(repr(result))."""
    src = ("import runpy, sys; sys.argv=['wiki']; g=runpy.run_path(%r); print(repr(eval(%r, g)))"
           % (ENGINE, code))
    import os
    env = {**os.environ, "WIKI_HOME": str(wiki)}
    return subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, env=env)

w = make_wiki()

# _repo_norm: slug == https == ssh; paths compare as paths; .git stripped
r = probe(w, "(_repo_norm('octocat/claude-wiki-memory'), "
             "_repo_norm('https://github.com/octocat/claude-wiki-memory.git'), "
             "_repo_norm('git@github.com:octocat/claude-wiki-memory.git'))")
a, b, c = eval(r.stdout.strip()); assert a == b == c, (a, b, c)
r = probe(w, "_repo_norm('/tmp/x/remote.git') == _repo_norm('/tmp/x/remote')")
assert r.stdout.strip() == "True", r.stdout + r.stderr

# _remote_state on local paths: empty bare / seeded bare / missing path
empty = make_origin()
r = probe(w, "_remote_state(%r)[0]" % str(empty)); assert "empty" in r.stdout, r.stdout + r.stderr
full = make_origin(); seed_origin(full, {"journal/2026/07/x.md": "j\n"})
r = probe(w, "_remote_state(%r)[0]" % str(full)); assert "has_main" in r.stdout
r = probe(w, "_remote_state('/nonexistent/nowhere.git')[0]")
assert "unreachable" in r.stdout, "missing local path must be unreachable, never absent"

# signals: corpus present in make_wiki; worktree_emptied on full deletion, NOT on mixed damage
r = probe(w, "(_local_state()['has_corpus'], _local_state()['is_repo'])")
assert r.stdout.strip() == "(True, True)", r.stdout + r.stderr
for t in sh(w, "git", "ls-files").stdout.splitlines(): (w / t).unlink()
r = probe(w, "_worktree_emptied()"); assert r.stdout.strip() == "True", r.stdout + r.stderr
sh(w, "git", "checkout", "--", ".gitignore")          # one file back → mixed
(w / ".gitignore").write_text("edited\n")
r = probe(w, "_worktree_emptied()"); assert r.stdout.strip() == "False", "mixed damage must not be 'emptied'"

# has_corpus: junk files are not a corpus — a lone journal/.DS_Store must read False
import tempfile, os
junkw = Path(tempfile.mkdtemp(prefix="wiki5_"))
(junkw / "journal").mkdir()
(junkw / "journal" / ".DS_Store").write_text("junk")
r = probe(junkw, "_local_state()['has_corpus']")
assert r.stdout.strip() == "False", "junk-only journal/ must not count as corpus: " + r.stdout + r.stderr

# _init_locks under contention: held record.lock → loud wait message, then acquisition
lockw = Path(tempfile.mkdtemp(prefix="wiki5_"))
(lockw / "state").mkdir()
holder_src = ("import fcntl, time; f = open(%r, 'w'); fcntl.flock(f, fcntl.LOCK_EX); "
              "print('HELD', flush=True); time.sleep(2)" % str(lockw / "state" / "record.lock"))
holder = subprocess.Popen([sys.executable, "-c", holder_src], stdout=subprocess.PIPE, text=True)
assert holder.stdout.readline().strip() == "HELD", "lock holder failed to start"
child_src = ("import runpy, sys; sys.argv=['wiki']; g=runpy.run_path(%r); "
             "ctx = g['_init_locks'](); ctx.__enter__(); print('GOT'); ctx.__exit__(None, None, None)"
             % ENGINE)
r = subprocess.run([sys.executable, "-c", child_src], capture_output=True, text=True,
                   env={**os.environ, "WIKI_HOME": str(lockw)}, timeout=30)
holder.wait(); holder.stdout.close()
assert "waiting for in-flight wiki jobs" in r.stdout, "must warn loudly on contention: " + r.stdout + r.stderr
assert "GOT" in r.stdout, "must acquire after holder exits: " + r.stdout + r.stderr

# F2: WIKI nested inside an ancestor repo (with its own origin), WIKI's own .git EXISTS but is
# EMPTY (present, not a valid repo marker — git discovery walks straight past it to the
# ancestor: `rev-parse --show-toplevel` resolves to the ancestor, empirically confirmed).
# _own_repo()/is_repo/has_origin must all read False — never let the ancestor answer on WIKI's
# behalf (pre-fix: is_repo and has_origin both read True from the ancestor's remote).
import shutil as _sh2
outer2 = Path(tempfile.mkdtemp(prefix="f2outer_"))
subprocess.run(["git", "init", "-q", "-b", "main"], cwd=outer2)
subprocess.run(["git", "config", "user.email", "t@t"], cwd=outer2)
subprocess.run(["git", "config", "user.name", "t"], cwd=outer2)
(outer2 / "README.md").write_text("outer project\n")
subprocess.run(["git", "add", "-A"], cwd=outer2)
subprocess.run(["git", "commit", "-q", "-m", "outer seed"], cwd=outer2)
ancestor_origin = make_origin()
subprocess.run(["git", "remote", "add", "origin", str(ancestor_origin)], cwd=outer2)

w2b = outer2 / "inner" / "wiki"
(w2b / "pages" / "topics").mkdir(parents=True)
(w2b / "journal" / "2026" / "07").mkdir(parents=True)
(w2b / "journal" / "2026" / "07" / "a.md").write_text("session notes\n")
(w2b / ".git").mkdir(parents=True)                       # EMPTY .git dir — present but invalid

r = probe(w2b, "_own_repo()")
assert r.stdout.strip() == "False", "own_repo must be False for an empty nested .git: " + r.stdout + r.stderr
r = probe(w2b, "_local_state()['is_repo']")
assert r.stdout.strip() == "False", "is_repo must be False for an empty nested .git: " + r.stdout + r.stderr
r = probe(w2b, "_local_state()['has_origin']")
assert r.stdout.strip() == "False", "has_origin must be False — the ancestor must never answer: " + r.stdout + r.stderr

print("ok test_init_state")
