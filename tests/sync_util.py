# tests/sync_util.py — shared harness: throwaway WIKI_HOME git repos + a local bare "origin".
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent      # tests/ lives at <repo>/tests/
ENGINE = str(ROOT / "bin" / "wiki")

def sh(cwd, *args, input=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, input=input)

def must(r, msg="setup command failed"):
    """Assert a setup step's rc — silent seed failures otherwise misdiagnose later asserts."""
    assert r.returncode == 0, "%s: %s%s" % (msg, r.stdout, r.stderr)
    return r

def make_wiki(branch="main"):
    """Throwaway data repo: git init + identity + minimal wiki layout + one seed commit."""
    d = Path(tempfile.mkdtemp(prefix="wiki5_"))
    sh(d, "git", "init", "-q", "-b", branch)
    sh(d, "git", "config", "user.email", "t@t")
    sh(d, "git", "config", "user.name", "t")
    (d / "pages" / "topics").mkdir(parents=True)
    (d / "journal" / "2026" / "07").mkdir(parents=True)
    (d / "state").mkdir()
    (d / "logs").mkdir()
    (d / "config.json").write_text('{"enabled": true}')
    (d / ".gitignore").write_text("state/\nlogs/\n*.db*\n.githooks/\n")
    (d / "pages" / "topics" / "seed.md").write_text("---\nname: Seed\n---\nseed page\n")
    sh(d, "git", "add", "-A")
    sh(d, "git", "commit", "-q", "-m", "seed")
    return d

def make_origin(branch="main"):
    # -b main is REQUIRED: a default `git init --bare` leaves HEAD → refs/heads/master (this
    # machine has no init.defaultBranch), so clones of a main-only bare check out an EMPTY
    # worktree and every subsequent seed push fails silently.
    b = Path(tempfile.mkdtemp(prefix="origin5_")) / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", branch, str(b)])
    return b

def seed_origin(origin, files, branch="main"):
    """Populate a bare origin: temp clone → write files → push. Returns the temp worktree."""
    d = Path(tempfile.mkdtemp(prefix="seed5_")) / "w"
    must(subprocess.run(["git", "clone", "-q", str(origin), str(d)],
                        capture_output=True, text=True), "clone for seeding")
    sh(d, "git", "config", "user.email", "t@t"); sh(d, "git", "config", "user.name", "t")
    sh(d, "git", "checkout", "-q", "-B", branch)
    for rel, content in files.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
    sh(d, "git", "add", "-A"); must(sh(d, "git", "commit", "-q", "-m", "seed"), "seed commit")
    must(sh(d, "git", "push", "-q", "origin", branch), "seed push")
    return d

def wire_origin(wiki, origin):
    sh(wiki, "git", "remote", "add", "origin", str(origin))

def enable_sync(wiki, branch="main", auto_push=True):
    # No `remote` key — the engine always uses git's "origin" (WP5 removed the dead sync.remote knob).
    (wiki / "state" / "config.local.json").write_text(
        '{"sync": {"enabled": true, "branch": "%s", "auto_push": %s}}'
        % (branch, "true" if auto_push else "false"))

def run(args, wiki, input=None):
    env = {**os.environ, "WIKI_HOME": str(wiki)}
    return subprocess.run([sys.executable, ENGINE] + args, capture_output=True,
                          text=True, env=env, input=input)

def commit_file(wiki, rel, content, msg="c"):
    p = wiki / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    sh(wiki, "git", "add", "--", rel)
    sh(wiki, "git", "commit", "-q", "-m", msg, "--", rel)

def origin_main_sha(origin, branch="main"):
    r = subprocess.run(["git", "ls-remote", "--heads", str(origin), branch],
                       capture_output=True, text=True)
    return r.stdout.split()[0] if r.stdout.strip() else None
