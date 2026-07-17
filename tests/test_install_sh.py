# tests/test_install_sh.py — installer: syntax, pinned-release gate (exact-match + auto-recover),
# exec/arg forwarding, gh preflight (fakes).
import os, re, shutil, subprocess, tempfile, json
from pathlib import Path
from sync_util import ROOT
SH = ROOT / "install.sh"
# DERIVE the pinned version from install.sh itself so the test can never drift out of sync with a
# release bump (a hardcoded literal here silently broke when EXPECT moved 0.1.0 -> 0.1.1).
_m = re.search(r'(?m)^EXPECT="([^"]+)"', SH.read_text())
assert _m, "could not find EXPECT=\"...\" in install.sh"
EXPECT = _m.group(1)

assert subprocess.run(["bash", "-n", str(SH)]).returncode == 0, "bash -n failed"

def fake_env(version=EXPECT, readd_version=EXPECT, listed=True, enabled=True, gh="authed"):
    # gh ∈ {"authed","unauthed","missing"} models the WP2 gh preflight: authed → a fake gh whose
    # `auth status` exits 0; unauthed → present but `auth status` exits 1; missing → no gh anywhere
    # on a SEALED PATH (so a real host gh can't leak in and flake the test).
    #
    # version       = manifest version the marketplace clone STARTS at (stale pre-reset clones keep
    #                 a 1.x here forever — their `git pull` can't cross the fresh-root history).
    # readd_version = manifest version a `marketplace remove` + `marketplace add` re-clone yields.
    #                 The fake `marketplace add` writes it ONLY if the manifest is absent (a real
    #                 add no-ops when the marketplace already exists; only post-remove does it
    #                 clone fresh). EXPECT proves the auto-recover happy path; a wrong value
    #                 proves the loud-fail path.
    d = Path(tempfile.mkdtemp(prefix="fake5_"))
    home = d / "home"; mp = home / ".claude" / "plugins" / "marketplaces" / "claude-wiki"
    (mp / ".claude-plugin").mkdir(parents=True)
    manifest = mp / ".claude-plugin" / "plugin.json"
    manifest.write_text(json.dumps({"name": "wiki", "version": version}))
    # LIVE-VERIFIED shape of real `claude plugin list` output (checked against the claude CLI at
    # the pre-release gate): "  ❯ name@marketplace" line, then indented Version/Scope/Status
    # lines — Status ("✔ enabled" / "✘ disabled") sits 3 lines below, hence install.sh's grep -A3.
    listing = ("  > wiki@claude-wiki\n    Version: %s\n    Scope: user\n    Status: %s\n"
               % (EXPECT, "enabled" if enabled else "disabled")) if listed else "none\n"
    log = d / "claude.log"
    readd_json = json.dumps({"name": "wiki", "version": readd_version})
    (d / "claude").write_text(
        '#!/bin/sh\n'
        'echo "$@" >> "%s"\n' % log +
        'if [ "$1" = plugin ] && [ "$2" = list ]; then printf \'%s\'; fi\n'
        % listing.replace("\n", "\\n") +
        'if [ "$1" = plugin ] && [ "$2" = marketplace ] && [ "$3" = remove ]; then rm -f "%s"; fi\n'
        % manifest +
        'if [ "$1" = plugin ] && [ "$2" = marketplace ] && [ "$3" = add ] && [ ! -f "%s" ]; then '
        "printf '%%s' '%s' > \"%s\"; fi\n" % (manifest, readd_json, manifest) +
        'exit 0\n')
    # install.sh always runs `python3 "$ENGINE" ...` (never execs $ENGINE directly via its own
    # shebang — see bin/wiki's own #!/usr/bin/env python3 and every other test's
    # `[sys.executable, ENGINE, ...]` invocation), so the fake engine must be valid Python, not sh.
    (d / "engine").write_text("import sys\nprint('ENGINE-CALLED', *sys.argv[1:])\n")
    execs = ["claude", "engine"]
    if gh in ("authed", "unauthed"):
        (d / "gh").write_text("#!/bin/sh\nif [ \"$1\" = auth ] && [ \"$2\" = status ]; then exit %d; fi\n"
                              "exit 0\n" % (0 if gh == "authed" else 1))
        execs.append("gh")
    for f in execs: os.chmod(d / f, 0o755)
    path = str(d) + os.pathsep + os.environ["PATH"]
    if gh == "missing":
        # Seal PATH to the fake dir + a bin of ONLY the tools install.sh touches before the gh
        # check (claude is the fake above; git/python3 real); gh is deliberately absent so
        # `need gh` fails deterministically regardless of what the host has installed.
        sealed = d / "sealedbin"; sealed.mkdir()
        for t in ("bash", "git", "python3", "sh", "grep"):  # bash: subprocess resolves it via env PATH
            src = shutil.which(t)
            if src: os.symlink(src, sealed / t)
        path = str(d) + os.pathsep + str(sealed)
    env = {**os.environ, "HOME": str(home), "PATH": path,
           "WIKI_INSTALL_ENGINE": str(d / "engine")}
    return env

def run_sh(env, *args):
    return subprocess.run(["bash", str(SH), *args], capture_output=True, text=True, env=env)

def claude_log(env):
    p = Path(env["WIKI_INSTALL_ENGINE"]).parent / "claude.log"
    return p.read_text() if p.exists() else ""

env = fake_env()                                          # success (gh authed): execs engine, no TARGET
r = run_sh(env)
assert r.returncode == 0 and "ENGINE-CALLED init --yes" in r.stdout, r.stdout + r.stderr
assert "marketplace remove" not in claude_log(env), \
    "happy path must not trigger the remove+re-add recovery\n" + claude_log(env)
r = run_sh(fake_env(), "someone/repo")                    # TARGET forwarded
assert "ENGINE-CALLED init someone/repo --yes" in r.stdout, r.stdout
# WP2 gh preflight — default (no-arg) path requires gh present AND authenticated:
r = run_sh(fake_env(gh="unauthed"))                       # gh present but not logged in → clean exit 1
assert r.returncode == 1 and "gh auth login" in r.stderr, r.stdout + r.stderr
r = run_sh(fake_env(gh="missing"))                        # gh not installed → clean exit 1 (need gh)
assert r.returncode == 1 and "'gh' not found" in r.stderr, r.stdout + r.stderr
r = run_sh(fake_env(gh="unauthed"), "someone/repo")       # explicit TARGET must NOT trip gh preflight
assert r.returncode == 0 and "ENGINE-CALLED init someone/repo --yes" in r.stdout, r.stdout + r.stderr
r = run_sh(fake_env(listed=False))                        # not installed → exit 1 (F9)
assert r.returncode == 1, r.stdout + r.stderr
r = run_sh(fake_env(enabled=False))                       # installed-but-disabled → exit 1 (R12a)
assert r.returncode == 1, r.stdout + r.stderr
# Pinned-release gate (post-reset): the manifest must EXACTLY equal EXPECT — a stale pre-reset
# clone can't `git pull` across the fresh root, so any mismatch means an unknown engine.
# AUTO-RECOVER happy path: stale 1.2.0 clone → remove + re-add yields EXPECT → proceeds.
env = fake_env(version="1.2.0", readd_version=EXPECT)
r = run_sh(env)
assert r.returncode == 0 and "ENGINE-CALLED init --yes" in r.stdout, r.stdout + r.stderr
log = claude_log(env)
assert "plugin marketplace remove claude-wiki" in log, "recovery must remove the stale clone\n" + log
assert log.count("plugin marketplace add necatisozer/claude-wiki") == 2, \
    "recovery must re-add after remove\n" + log
# LOUD-FAIL path: remove + re-add STILL yields the wrong version → loud error, exit non-zero,
# and the engine must NEVER run.
env = fake_env(version="1.2.0", readd_version="1.2.0")
r = run_sh(env)
assert r.returncode == 1 and ("requires exactly %s" % EXPECT) in r.stderr, r.stdout + r.stderr
assert "ENGINE-CALLED" not in r.stdout, "must never run an unknown engine\n" + r.stdout
assert "plugin marketplace remove claude-wiki" in claude_log(env), \
    "loud-fail must still have attempted recovery first\n" + claude_log(env)
# EXACT match, not >=: a numerically-newer stale clone (pre-reset 1.10.0 beats 0.x forever)
# must be rejected too — the old tuple-compare gate would have silently passed it.
r = run_sh(fake_env(version="1.10.0", readd_version="1.10.0"))
assert r.returncode == 1 and "ENGINE-CALLED" not in r.stdout, \
    "1.10.0 must NOT satisfy the exact-match gate\n" + r.stdout + r.stderr
print("ok test_install_sh")
