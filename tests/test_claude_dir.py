# tests/test_claude_dir.py — run: python3 tests/test_claude_dir.py
#
# CLAUDE_CONFIG_DIR is Claude Code's own config-dir relocation knob. The engine must follow it —
# a relocated install otherwise leaves reconcile/backfill scanning an empty ~/.claude/projects and
# the version-parity checks reading plugin paths that no longer exist. Pins:
#   • CLAUDE_CONFIG_DIR set → PROJECTS and the default WIKI live under it;
#   • WIKI_HOME still wins over the CLAUDE_CONFIG_DIR-derived default (existing contract);
#   • unset → the stock ~/.claude fallback.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; env overridden BEFORE each import — the live wiki
# is never read or written.
import os, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="cd_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

def load(name):
    loader = importlib.machinery.SourceFileLoader(name, str(ENGINE))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(mod)
    return mod

# 1. CLAUDE_CONFIG_DIR set, WIKI_HOME unset → both PROJECTS and the default WIKI follow it.
cdir = _mkdtemp("cd_cfg_")
os.environ["CLAUDE_CONFIG_DIR"] = str(cdir)
os.environ.pop("WIKI_HOME", None)
w = load("wiki_engine_cd1")
assert w.PROJECTS == cdir / "projects", w.PROJECTS
assert w.WIKI == cdir / "wiki", w.WIKI
print("ok 1: CLAUDE_CONFIG_DIR moves PROJECTS and the default WIKI")

# 2. WIKI_HOME still wins over the CLAUDE_CONFIG_DIR-derived default.
data = _mkdtemp("cd_data_")
os.environ["WIKI_HOME"] = str(data)
w = load("wiki_engine_cd2")
assert w.WIKI == data and w.PROJECTS == cdir / "projects", (w.WIKI, w.PROJECTS)
print("ok 2: WIKI_HOME override still wins")

# 3. Neither set → stock ~/.claude fallback.
os.environ.pop("CLAUDE_CONFIG_DIR", None)
os.environ["WIKI_HOME"] = str(data)   # keep the live wiki out of reach; only PROJECTS is asserted
w = load("wiki_engine_cd3")
assert w.PROJECTS == Path.home() / ".claude" / "projects", w.PROJECTS
print("ok 3: unset → stock ~/.claude fallback")

print("PASS test_claude_dir")
