# tests/test_version_guard.py — v0.1.4 stale-cache engine guard: an engine executing from the
# version-keyed plugin cache must refuse hook-driven work (record/maintain) when its manifest
# version differs from the installed marketplace manifest; every other run location is exempt.
# Live incident this pins: 2026-07-19, a stale 0.1.0 cache engine ran scheduled lint with
# pre-0.1.2 rules and wrote 92 false findings.
#
# SAFETY: HOME + WIKI_HOME overridden to throwaways BEFORE import; the live wiki is never touched.
import os, json, shutil, tempfile, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="vg_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_FAKE_HOME = _mkdtemp("vg_home_")
os.environ["HOME"] = str(_FAKE_HOME)
os.environ["WIKI_HOME"] = str(_mkdtemp("vg_wiki_"))
_loader = importlib.machinery.SourceFileLoader("wiki_engine_vg", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_vg", _loader))
_loader.exec_module(wiki)
wiki.HOME = _FAKE_HOME                              # module snapshot of Path.home() — repoint explicitly

def _write_manifest(root, version):
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "wiki", "version": version}))

def _marketplace(version):
    mp = _FAKE_HOME / ".claude" / "plugins" / "marketplaces" / "claude-wiki"
    _write_manifest(mp, version)
    return mp

def _cache_engine_root(version):
    root = _FAKE_HOME / ".claude" / "plugins" / "cache" / "claude-wiki" / "wiki" / version
    _write_manifest(root, version)
    return root

ORIG_CODE_ROOT = wiki.CODE_ROOT

# 1. Engine in the version-keyed cache, version != installed → STALE (the incident case)
_marketplace("0.1.4")
wiki.CODE_ROOT = _cache_engine_root("0.1.0")
st = wiki._stale_cache_engine()
assert st == ("0.1.0", "0.1.4"), "cache engine 0.1.0 vs installed 0.1.4 must be stale: %r" % (st,)

# 2. Cache engine matching the installed version → fine
wiki.CODE_ROOT = _cache_engine_root("0.1.4")
assert wiki._stale_cache_engine() is None, "matching cache engine must not be stale"

# 3. Cache path but MISSING own manifest → malformed copy, still reported stale (fail-closed)
bare = _FAKE_HOME / ".claude" / "plugins" / "cache" / "claude-wiki" / "wiki" / "0.0.9"
bare.mkdir(parents=True, exist_ok=True)
wiki.CODE_ROOT = bare
st = wiki._stale_cache_engine()
assert st == ("unknown", "0.1.4"), "cache copy without a manifest must read as stale: %r" % (st,)

# 4. NON-cache locations never trip the guard, even on mismatch: dev checkout / marketplace clone
dev = _mkdtemp("vg_dev_")
_write_manifest(Path(dev), "9.9.9")
wiki.CODE_ROOT = Path(dev)
assert wiki._stale_cache_engine() is None, "a dev checkout must never trip the cache guard"
wiki.CODE_ROOT = _FAKE_HOME / ".claude" / "plugins" / "marketplaces" / "claude-wiki"
assert wiki._stale_cache_engine() is None, "the marketplace clone itself must never trip the guard"

# 5. No marketplace manifest visible (fresh machine / test HOME) → cannot judge → None
shutil.rmtree(_FAKE_HOME / ".claude" / "plugins" / "marketplaces" / "claude-wiki")
wiki.CODE_ROOT = _cache_engine_root("0.1.0")
assert wiki._stale_cache_engine() is None, "no installed manifest → guard must stand down"

# 6. cmd_record and cmd_maintain refuse (exit 0, no writes) under a stale cache engine
_marketplace("0.1.4")
wiki.CODE_ROOT = _cache_engine_root("0.1.0")
(wiki.WIKI / "state").mkdir(parents=True, exist_ok=True)
(wiki.WIKI / "config.json").write_text(json.dumps({"enabled": True, "schema_version": 2}))
rc = wiki.cmd_record(["--session", "00000000-0000-4000-8000-000000000000"])
assert rc == 0, "stale record must refuse cleanly"
assert not (wiki.WIKI / "journal").exists(), "stale record must write NO journal"
rc = wiki.cmd_maintain([])
assert rc == 0, "stale maintain must refuse cleanly"
assert not (wiki.WIKI / "state" / "last_ingest").exists(), "stale maintain must run NO jobs"
logf = wiki.WIKI / "logs" / "wiki.log"
logtxt = logf.read_text() if logf.exists() else ""
assert "record: REFUSED" in logtxt and "maintain: REFUSED" in logtxt, \
    "refusals must be logged for diagnosability:\n" + logtxt

# 7. Same calls with a MATCHING engine proceed past the guard (maintain runs its lock/jobs path)
wiki.CODE_ROOT = _cache_engine_root("0.1.4")
rc = wiki.cmd_maintain([])
assert rc == 0
wiki.CODE_ROOT = ORIG_CODE_ROOT
print("PASS test_version_guard")
