# tests/test_init_restore.py — rows 1/2c (sync/init design): clone-adopt, heal, refusals.
from sync_util import make_origin, seed_origin, run, sh, must, origin_main_sha
from pathlib import Path
import json, os, shutil, subprocess, tempfile

CORPUS = {"journal/2026/07/a.md": "session one\n",
          "pages/topics/t.md": "---\nname: T\ndescription: d\n---\nbody\n",
          "config.json": '{"enabled": true}\n', ".gitignore": "state/\nlogs/\n*.db*\n.githooks/\n"}

def fresh_home():
    return Path(tempfile.mkdtemp(prefix="home5_")) / "wiki"

# happy: absent WIKI → cloned, hook, armed; banner printed; re-run row-0 rc 0
o = make_origin(); seed_origin(o, CORPUS)
w = fresh_home()
r = run(["init", str(o), "--yes"], w)
assert r.returncode == 0, r.stdout + r.stderr
assert "auto-sync will be armed on this device" in r.stdout, "banner must print under --yes"
assert (w / "journal" / "2026" / "07" / "a.md").exists() and (w / ".githooks" / "pre-push").exists()
assert '"enabled": true' in (w / "state" / "config.local.json").read_text()
assert not (w.parent / (w.name + ".init-restore.tmp")).exists(), "temp cleaned (F12/R10)"
assert run(["init"], w).returncode == 0

# state-only WIKI (P1): pre-seeded state/ + logs/ survive
w2 = fresh_home(); (w2 / "state").mkdir(parents=True); (w2 / "logs").mkdir()
(w2 / "state" / "keep.txt").write_text("x")
r = run(["init", str(o), "--yes"], w2)
assert r.returncode == 0 and (w2 / "state" / "keep.txt").read_text() == "x", r.stdout + r.stderr

# real content → refuse, nothing cloned
w3 = fresh_home(); (w3 / "journal" / "2026").mkdir(parents=True)
(w3 / "journal" / "2026" / "pre.md").write_text("recorded before restore\n")
r = run(["init", str(o), "--yes"], w3)
assert r.returncode == 1 and not (w3 / ".git").exists(), r.stdout + r.stderr

# half-restored (crash after .git move) → bare re-run heals from EXISTING origin (R4),
# removes stale temp (R10), then pull --rebase works (F4)
w4 = fresh_home(); w4.mkdir(parents=True)
must(subprocess.run(["git", "clone", "-q", str(o), str(w4.parent / "c")], capture_output=True, text=True))
os.replace(w4.parent / "c" / ".git", w4 / ".git")
shutil.rmtree(w4.parent / "c")
stale = w4.parent / (w4.name + ".init-restore.tmp"); stale.mkdir()
(stale / "leak.md").write_text("leftover corpus copy")
r = run(["init", "--yes"], w4)                      # note: NO TARGET — heals from origin
assert r.returncode == 0, r.stdout + r.stderr
assert (w4 / "journal" / "2026" / "07" / "a.md").exists() and not stale.exists()
assert must(sh(w4, "git", "pull", "--rebase", "origin", "main")).returncode == 0

# mixed damage: one deletion + one uncommitted edit → rc 1, edit byte-intact (R1)
w5 = fresh_home()
assert run(["init", str(o), "--yes"], w5).returncode == 0
(w5 / "journal" / "2026" / "07" / "a.md").unlink()
(w5 / "pages" / "topics" / "t.md").write_text("PRECIOUS UNCOMMITTED EDIT\n")
(w5 / "state" / "config.local.json").unlink()        # disarm → routes past row 0
r = run(["init", "--yes"], w5)
assert r.returncode == 1 and "worktree damaged" in r.stdout, r.stdout + r.stderr
assert (w5 / "pages" / "topics" / "t.md").read_text() == "PRECIOUS UNCOMMITTED EDIT\n"

# 2c explicit mismatching TARGET → rc 1
w6 = fresh_home(); w6.mkdir(parents=True)
must(subprocess.run(["git", "clone", "-q", str(o), str(w6.parent / "c6")], capture_output=True, text=True))
os.replace(w6.parent / "c6" / ".git", w6 / ".git"); shutil.rmtree(w6.parent / "c6")
r = run(["init", "/some/other/remote.git", "--yes"], w6)
assert r.returncode == 1 and "refusing different TARGET" in r.stdout

# master-default origin → armed branch matches (R11) and pull works
om = make_origin(branch="master"); seed_origin(om, CORPUS, branch="master")
w7 = fresh_home()
r = run(["init", str(om), "--yes"], w7)
assert r.returncode == 0, r.stdout + r.stderr
assert '"branch": "master"' in (w7 / "state" / "config.local.json").read_text()
assert must(sh(w7, "git", "pull", "--rebase", "origin", "master")).returncode == 0
# clone failure with a PASSING probe (refs intact, objects gutted): rc 1, WIKI untouched,
# never armed, temp cleaned (R10). Self-checking split: the banner proves the probe routed to
# row 1; "clone failed" proves the clone leg itself failed. A pre-seeded stale temp makes the
# tmp-absence assert discriminating even though git self-cleans its own failed clone target.
oc = make_origin(); seed_origin(oc, CORPUS)
shutil.rmtree(oc / "objects"); (oc / "objects").mkdir()  # ls-remote reads refs only; clone needs objects
w8 = fresh_home()
stale8 = w8.parent / (w8.name + ".init-restore.tmp"); stale8.mkdir(parents=True)
(stale8 / "leak.md").write_text("leftover")
r = run(["init", str(oc), "--yes"], w8)
assert "auto-sync will be armed on this device" in r.stdout, \
    "probe must still route to row 1:\n" + r.stdout + r.stderr
assert r.returncode == 1 and "clone failed" in r.stdout, r.stdout + r.stderr
assert not (w8 / ".git").exists() and not (w8 / "journal").exists() and not (w8 / "pages").exists()
assert not (w8 / "state" / "config.local.json").exists(), "must never arm on clone failure"
assert not stale8.exists(), "temp cleaned on clone failure (R10)"

# pre-existing auto_push=false survives arming (R11): unarmed device, preference already on disk
w9 = fresh_home(); (w9 / "state").mkdir(parents=True)
(w9 / "state" / "config.local.json").write_text('{"sync": {"auto_push": false}}')
r = run(["init", str(o), "--yes"], w9)
assert r.returncode == 0, r.stdout + r.stderr
cl = (w9 / "state" / "config.local.json").read_text()
assert '"auto_push": false' in cl and '"enabled": true' in cl, cl

# F3: master-default remote losing arming re-enters ROW 5 (repo+origin already wired locally —
# a straight `git clone`, NOT via _cmd_init_restore) — branch fidelity must be preserved. Row 5
# used to unconditionally rename master->main and push/arm "main"; against a master-default
# remote that forks it: a NEW main head gets pushed while the remote's default HEAD stays
# master, so the next device to restore still sees stale master.
om2 = make_origin(branch="master"); seed_origin(om2, CORPUS, branch="master")
w10 = fresh_home(); w10.mkdir(parents=True)
must(subprocess.run(["git", "clone", "-q", str(om2), str(w10)], capture_output=True, text=True))
sh(w10, "git", "config", "user.email", "t@t"); sh(w10, "git", "config", "user.name", "t")
assert sh(w10, "git", "branch", "--show-current").stdout.strip() == "master"
(w10 / "state").mkdir(exist_ok=True); (w10 / "logs").mkdir(exist_ok=True)

r = run(["init", "--yes"], w10)
assert r.returncode == 0, r.stdout + r.stderr
assert sh(w10, "git", "branch", "--show-current").stdout.strip() == "master", \
    "must NOT rename to main over a master-default remote: " + r.stdout + r.stderr
cl10 = json.loads((w10 / "state" / "config.local.json").read_text())
assert cl10["sync"]["branch"] == "master", "must arm with the ACTUAL branch, not hardcoded main: " + str(cl10)
assert origin_main_sha(om2, "main") is None, \
    "origin must gain NO main head — that IS the cross-device fork"
assert must(sh(w10, "git", "pull", "--rebase", "origin", "master")).returncode == 0

print("ok test_init_restore")
