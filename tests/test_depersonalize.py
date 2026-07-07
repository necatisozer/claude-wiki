# tests/test_depersonalize.py — WP2 "init / identity" de-personalization (run: python3 tests/test_depersonalize.py)
# Pins every WP2 row so the shipped engine derives repo + identity from the RUNNING USER's env and
# never bakes in the author's namespace/identity:
#   ROW 1  derived default slug <gh-login>/claude-wiki-memory + fail-closed when underivable
#   ROW 2  commits use the user's own git identity, neutral claude-wiki[bot] fallback only if unset
#   ROW 3  first-push scope banner prints even under --yes
#   ROW 4  transport allowlist on the init argument (reject ext::/fd::/option-injection/'::')
#   ROW 6  doctor reports a gh presence/auth line
# All state lives in tempdirs with WIKI_HOME/HOME/PATH overridden — no test touches the live repo.
# No secret-shaped literals appear, so `wiki _scan-selftest` stays clean.
import ast, json, os, subprocess, sys, tempfile
from pathlib import Path
from sync_util import ENGINE, make_wiki, make_origin, wire_origin, run

AUTHOR = "necatisozer"     # the author's namespace — must NEVER appear in any shipped output

def fake_gh(where, body):
    """Write an executable fake `gh` shim (POSIX sh) into a fresh dir, return that dir for PATH."""
    d = Path(where); d.mkdir(parents=True, exist_ok=True)
    (d / "gh").write_text("#!/bin/sh\n" + body)
    (d / "gh").chmod(0o755)
    return d

def run_env(args, wiki, path_prepend=None, extra_env=None, input=None):
    env = {**os.environ, "WIKI_HOME": str(wiki)}
    if path_prepend:
        env["PATH"] = str(path_prepend) + os.pathsep + os.environ["PATH"]
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, ENGINE] + args, capture_output=True, text=True,
                          env=env, input=input)

def probe(wiki, code, path_prepend=None):
    """Evaluate an engine-internal expression in a subprocess and print its repr(). `code` is always a
    string LITERAL written in this file (never external input) — the same test-only probe pattern as
    tests/test_init_state.py; the in-child eval is how the engine module's helpers are reached."""
    src = "import runpy, sys; sys.argv=['wiki']; g=runpy.run_path(%r); print(repr(eval(%r, g)))" % (ENGINE, code)
    env = {**os.environ, "WIKI_HOME": str(wiki)}
    if path_prepend:
        env["PATH"] = str(path_prepend) + os.pathsep + os.environ["PATH"]
    return subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, env=env)

def tmpdir(p="dep_"):
    return Path(tempfile.mkdtemp(prefix=p))

# ---------------------------------------------------------------- ROW 1 — derived default slug
# happy path: a fake `gh api user` login → default slug is <login>/claude-wiki-memory (exact)
t = tmpdir(); w = t / "wiki"; w.mkdir(parents=True)
gh_login = fake_gh(t / "gh_login",
    'if [ "$1" = api ] && [ "$2" = user ]; then printf \'{"login": "octo-user"}\'; exit 0; fi\nexit 1\n')
r = probe(w, "_default_slug()", path_prepend=gh_login)
assert r.stdout.strip() == repr("octo-user/claude-wiki-memory"), r.stdout + r.stderr
assert AUTHOR not in (r.stdout + r.stderr)

# end-to-end: no target + fake gh login → the DERIVED slug is what init tries to create (not the author's)
w1 = tmpdir() / "wiki"; w1.mkdir(parents=True)
gh_flow = fake_gh(tmpdir("dep_gh_"),
    'case "$1 $2" in\n'
    '  "api user") printf \'{"login": "octo-user"}\'; exit 0;;\n'
    '  "repo view") echo "GraphQL: Could not resolve to a Repository ($3)" >&2; exit 1;;\n'
    '  "repo create") echo "fake refuses to create $3" >&2; exit 1;;\n'
    'esac\n'
    'exit 1\n')
r = run_env(["init", "--yes"], w1, path_prepend=gh_flow)
out = r.stdout + r.stderr
assert r.returncode != 0, out
assert "octo-user/claude-wiki-memory" in out, "derived slug must flow into the repo-create attempt:\n" + out
assert AUTHOR not in out, "author default must NEVER appear:\n" + out

# fail-closed: gh unauthenticated (api user exits 1) + NO explicit target → abort, nonzero, actionable,
# no author fallback, and NO mutation of the data dir
w2 = tmpdir() / "wiki"; w2.mkdir(parents=True)
gh_unauth = fake_gh(tmpdir("dep_gh_"),
    'echo "gh: You are not logged into any GitHub hosts. Run: gh auth login" >&2\nexit 1\n')
r = run_env(["init", "--yes"], w2, path_prepend=gh_unauth)
out = r.stdout + r.stderr
assert r.returncode == 2, "fail-closed must exit nonzero (2): rc=%s\n%s" % (r.returncode, out)
assert "gh auth login" in out and "owner/repo" in out, "message must be actionable:\n" + out
assert AUTHOR not in out, "fail-closed must NOT fall back to any author default:\n" + out
assert not (w2 / ".git").exists(), "fail-closed must not mutate the data dir"

# ---------------------------------------------------------------- ROW 2 — git commit identity
# no identity anywhere (bare CI: no local/global/system user.*) → commit still succeeds as the neutral bot
tid = tmpdir("dep_id_"); wid = tid / "wiki"
subprocess.run(["git", "init", "-q", "-b", "main", str(wid)], check=True)
home0 = tid / "home"; home0.mkdir()
noident = {**os.environ, "WIKI_HOME": str(wid), "HOME": str(home0),
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
bot_src = (
    "import runpy, sys; sys.argv=['wiki']; g=runpy.run_path(" + repr(ENGINE) + ");\n"
    "(g['WIKI']/'f.txt').write_text('x\\n');\n"
    "r=g['git_commit_paths']('bot commit','f.txt');\n"
    "assert r.returncode==0, (r.stdout, r.stderr);\n"
    "print(g['git']('log','-1','--format=%an <%ae>').stdout.strip())\n")
r = subprocess.run([sys.executable, "-c", bot_src], capture_output=True, text=True, env=noident)
assert r.returncode == 0, r.stdout + r.stderr
assert r.stdout.strip() == "claude-wiki[bot] <claude-wiki[bot]@users.noreply.github.com>", r.stdout + r.stderr
assert AUTHOR not in (r.stdout + r.stderr)

# a real configured identity is used verbatim — never overridden by the engine
subprocess.run(["git", "-C", str(wid), "config", "user.name", "Real Dev"], check=True)
subprocess.run(["git", "-C", str(wid), "config", "user.email", "real@dev.example"], check=True)
real_src = (
    "import runpy, sys; sys.argv=['wiki']; g=runpy.run_path(" + repr(ENGINE) + ");\n"
    "(g['WIKI']/'f2.txt').write_text('y\\n');\n"
    "r=g['git_commit_paths']('real commit','f2.txt');\n"
    "assert r.returncode==0, (r.stdout, r.stderr);\n"
    "print(g['git']('log','-1','--format=%an').stdout.strip())\n")
r = subprocess.run([sys.executable, "-c", real_src], capture_output=True, text=True, env=noident)
assert r.returncode == 0, r.stdout + r.stderr
assert r.stdout.strip() == "Real Dev", r.stdout + r.stderr

# ---------------------------------------------------------------- ROW 3 — first-push scope banner
# row-5 attach (repo + pre-wired origin) under --yes → banner still printed, disclosing the remote
wb = make_wiki(); ob = make_origin(); wire_origin(wb, ob)
r = run(["init", "--yes"], wb)
out = r.stdout + r.stderr
assert r.returncode == 0, out
assert "first-push scope" in out, "scope banner must print even under --yes:\n" + out
assert str(ob) in out, "banner must disclose the resolved remote:\n" + out

# ---------------------------------------------------------------- ROW 4 — transport allowlist
wt = tmpdir() / "wiki"; wt.mkdir(parents=True)
accept = ["owner/repo", "https://github.com/o/r", "git@github.com:o/r.git"]
reject = ["ext::sh -c whoami", "-oProxyCommand=x", "::x", "-flag", "fd::17"]
r = probe(wt, "[_validate_init_target(t)[0] for t in %r]" % (accept + reject))
got = ast.literal_eval(r.stdout.strip())    # safe: parses only the printed list-of-bools literal
assert got == [True, True, True, False, False, False, False, False], (got, r.stderr)
# end-to-end: a rejected transport must exit nonzero and never reach git/gh (no mutation)
r = run(["init", "ext::sh -c whoami", "--yes"], wt)
out = r.stdout + r.stderr
assert r.returncode == 2 and "refusing target" in out, out
assert not (wt / ".git").exists(), "rejected target must not mutate the data dir"

# ---------------------------------------------------------------- ROW 6 — doctor gh line
wd = tmpdir("dep_doc_")
(wd / "config.json").write_text('{"enabled": true}')
r = run(["doctor"], wd)
assert r.returncode == 0, r.stdout + r.stderr
assert "gh" in r.stdout, "doctor must report a gh presence/auth line:\n" + r.stdout

print("PASS test_depersonalize")
