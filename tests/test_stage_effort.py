# tests/test_stage_effort.py — run: python3 tests/test_stage_effort.py
#
# v0.1.19 — two ingest hardenings found on a live wiki whose fold had timed out daily for 2 weeks:
#   (1) per-stage `--effort` is passed EXPLICITLY to every `claude -p` call, so the headless engine
#       never inherits the user's interactive `effortLevel` (a global xhigh pushed every phase-② fold
#       past its 600s timeout). Config `<stage>.effort` overrides; "" / "inherit" omits the flag.
#   (2) elision hold: a fold that replaces an existing section with a placeholder ("(unchanged — see
#       prior entries)") is held with an explicit reason — accepting it would delete the section.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; HOME + WIKI_HOME overridden BEFORE import — the live
# wiki and ~/.claude/settings*.json are never read or written. No credential-shaped literals.
import os, sys, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="se_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

os.environ["HOME"] = str(_mkdtemp("se_home_"))
os.environ["WIKI_HOME"] = str(_mkdtemp("se_import_"))
_loader = importlib.machinery.SourceFileLoader("wiki_engine_se", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_se", _loader))
_loader.exec_module(wiki)

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

# ---- (1) effort plumbing -------------------------------------------------------------------------
check("defaults: ingest=medium", wiki._stage_effort({}, "ingest") == "medium")
check("defaults: record=low", wiki._stage_effort({}, "record") == "low")
check("config override", wiki._stage_effort({"lint": {"effort": "HIGH"}}, "lint") == "high")
check("inherit omits", wiki._stage_effort({"ingest": {"effort": "inherit"}}, "ingest") is None)
check("empty omits", wiki._stage_effort({"ingest": {"effort": ""}}, "ingest") is None)
argv = wiki._claude_argv("sonnet", "sys", "medium")
check("argv carries --effort", argv[-2:] == ["--effort", "medium"])
check("argv keeps json contract", "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json")
check("argv without effort unchanged", "--effort" not in wiki._claude_argv("sonnet", "sys"))

# call_claude really forwards effort to the subprocess
seen = {}
class _R:
    returncode, stderr, stdout = 0, "", '{"result": "ok", "is_error": false, "total_cost_usd": 0}'
_orig = wiki.subprocess.run
def _fake_run(argv, **kw):
    seen["argv"] = argv; return _R()
wiki.subprocess.run = _fake_run
try:
    out, _ = wiki.call_claude("sys", "user", "sonnet", effort="low")
finally:
    wiki.subprocess.run = _orig
check("call_claude forwards effort", seen["argv"][-2:] == ["--effort", "low"] and out == "ok")

# config validation accepts the new key and rejects a bogus level
schema = wiki._config_schema()
check("schema knows ingest.effort", "effort" in schema["ingest"])
check("valid level passes", wiki._check_value("c", "ingest.effort", "medium", str) == [])
check("bogus level flagged", wiki._check_value("c", "ingest.effort", "turbo", str) != [])

# ---- (2) elision guard ---------------------------------------------------------------------------
HEAD = "# P\n\n### Core Stack\n- Molecule state\n- Metro DI\n\n## Sources\n- 2026-07-01 · seed0001 · s\n"
ELIDED = "# P\n\n### Core Stack\n(unchanged — Molecule state management, Metro DI — see prior entries)\n\n## Sources\n- 2026-07-01 · seed0001 · s\n"
check("elision detected on tracked page", wiki._elision_hits(HEAD, ELIDED) > 0)
check("carried-over phrasing detected", wiki._elision_hits(HEAD, HEAD + "- (carried over — see prior entries for full list)\n") > 0)
check("new page exempt", wiki._elision_hits(None, ELIDED) == 0)
check("legit update not flagged", wiki._elision_hits(HEAD, HEAD.replace("- Metro DI", "- Metro DI 1.3.2 (landed 2026-07-21)")) == 0)
check("pre-existing placeholder not re-flagged", wiki._elision_hits(ELIDED, ELIDED + "- new fact\n") == 0)

sys.exit(1 if FAILS else 0)
