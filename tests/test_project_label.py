# tests/test_project_label.py — run: python3 tests/test_project_label.py
#
# project_label identifies a session's project by its REPOSITORY, not its directory.
#
# The bug this pins: the label used to be the cwd basename, so every git worktree
# (`…/.worktrees/issue-42`), scratch dir and `~/Downloads` became a project of its own —
# and because a rename moves the checkout but not the repo, one project's sessions could be
# folded into another project's page. Blocks 1-3 below are the regression.
#
# It also pins what must NOT change: the basename fallback (every pre-existing label was
# derived from it, so repos whose directory already matches their remote keep their label),
# the unconditional HOME special case, and fail-quiet behavior on junk input.
#
# SAFETY: every repo here is a tempfile.mkdtemp() with a fabricated https remote that is never
# contacted (`remote get-url` reads .git/config only). All owner/repo names are invented
# fixtures. The live wiki is never touched; HOME is overridden per-case by reloading the
# module, not by mutating the environment globally.
import os, sys, importlib.util, tempfile, subprocess, shutil, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def mkdtemp(prefix):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return d
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

def load_engine(home=None):
    """Import bin/wiki as a module (it is extensionless, hence spec_from_file_location on a
    copy). HOME is set before import because the module binds HOME at import time."""
    env_home = os.environ.get("HOME")
    if home:
        os.environ["HOME"] = home
    try:
        dst = Path(mkdtemp("pl_mod_")) / "wikimod.py"
        shutil.copy(ENGINE, dst)
        spec = importlib.util.spec_from_file_location("wikimod_%d" % len(_TMP), dst)
        m = importlib.util.module_from_spec(spec)
        argv = sys.argv[:]
        sys.argv = ["wiki", "--help"]
        try:
            spec.loader.exec_module(m)          # prints usage + SystemExit on --help
        except SystemExit:
            pass
        finally:
            sys.argv = argv
        return m
    finally:
        if env_home is not None:
            os.environ["HOME"] = env_home

def git(*a, cwd):
    return subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True)

def mkrepo(parent, name, origin):
    """A real repo with a fabricated (never-contacted) origin."""
    p = os.path.join(parent, name)
    os.makedirs(p, exist_ok=True)
    git("init", "-q", "-b", "main", cwd=p)
    if origin:
        git("remote", "add", "origin", origin, cwd=p)
    git("-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-q", "--allow-empty", "-m", "init", cwd=p)
    return p

m = load_engine()
pl, ru = m.project_label, m._repo_name_from_url
fails = []
def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r, want %r" % (label, got, want))
    print(("  ok   " if ok else "  FAIL ") + "%-42s %r" % (label, got))

# ---- 1. THE REGRESSION: a worktree is labeled by its repo, not by the worktree dir ----------
print("1. worktree / subdir attribution")
base = mkdtemp("pl_wt_")
repo = mkrepo(base, "checkout-renamed-since",          # dir name deliberately != repo name
              "https://github.com/acme/payments-api.git")
wt = os.path.join(base, ".worktrees", "issue-42")
git("worktree", "add", "-q", wt, "-b", "issue-42", cwd=repo)
check("worktree .worktrees/issue-42", pl(wt), "payments-api")
deep = os.path.join(repo, "feature", "billing", "src")
os.makedirs(deep, exist_ok=True)
check("subdirectory feature/billing/src", pl(deep), "payments-api")
check("renamed checkout dir", pl(repo), "payments-api")  # dir says checkout-renamed-since

# ---- 2. remote URL forms all yield the same repo name ---------------------------------------
print("\n2. remote URL parsing")
for url, want in [
        ("https://github.com/acme/payments-api.git", "payments-api"),
        ("https://github.com/acme/payments-api",     "payments-api"),
        ("git@github.com:acme/payments-api.git",     "payments-api"),
        ("ssh://git@github.com:22/acme/payments-api.git", "payments-api"),
        ("/srv/mirrors/payments-api.git/",           "payments-api"),
        ("https://h/o/payments-api.git?ref=x",       "payments-api")]:
    check(url, ru(url), want)

# ---- 3. a malformed remote must fall back, never mint a malformed project -------------------
print("\n3. malformed remotes reject (→ basename fallback)")
for url in ["", "   ", "https://h/o/.git", "https://h/o/bad name.git",
            "git@h:o/..", "https://h/o/" + "x" * 65]:
    check("reject %r" % url, ru(url), None)
# nested paths are NOT malformed — a GitLab subgroup remote is the repo's real URL and the
# repo name is still the last segment, so this must resolve rather than fall back.
check("gitlab subgroup nesting", ru("https://gitlab.com/group/sub/design-system.git"),
      "design-system")
badrepo = mkrepo(base, "scratchdir", "https://h/o/bad name.git")
check("repo w/ unusable origin → basename", pl(badrepo), "scratchdir")

# ---- 4. fallback preserved for everything with no repo / no origin --------------------------
print("\n4. basename fallback (pre-existing behavior)")
noorigin = mkrepo(base, "fresh-unpushed", None)
check("repo with no origin", pl(noorigin), "fresh-unpushed")
plain = os.path.join(base, "Downloads"); os.makedirs(plain, exist_ok=True)
check("non-repo directory", pl(plain), "Downloads")
check("nonexistent path", pl("/nonexistent/zzz/alpha"), "alpha")
check("empty cwd", pl(None), "unknown")
check("bare basename path", pl("/x/y/alpha"), "alpha")   # test_digest_redesign relies on this

# ---- 5. HOME wins unconditionally, even when ~ is itself a checkout -------------------------
print("\n5. HOME special case (WP2 ROW 5)")
fake_home = mkrepo(mkdtemp("pl_home_"), "myuser", "https://github.com/acme/dotfiles.git")
mh = load_engine(home=fake_home)
check("HOME that is a dotfiles repo", mh.project_label(fake_home), "home")
check("non-HOME sibling still uses remote", mh.project_label(
    mkrepo(os.path.dirname(fake_home), "other",
           "https://github.com/acme/design-system.git")), "design-system")

# ---- 6. the label is cached per process (reconcile/backfill label in a loop) -----------------
print("\n6. caching")
import time
pl(repo)                                              # warm
t0 = time.time()
for _ in range(300):
    pl(repo)
ms = (time.time() - t0) * 1000
check("300 cached calls < 50ms", ms < 50, True)
print("       (%.1f ms)" % ms)

print("\n%d checks failed" % len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
