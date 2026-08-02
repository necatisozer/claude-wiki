# tests/test_scrub_scan.py — run: python3 tests/test_scrub_scan.py
#
# Retro-scrub of the synced transcript tier: each transcripts/*.jsonl.gz was redacted with
# UPLOAD-DAY patterns and committed forever, so every later pattern improvement creates a blind
# spot. _scrub_scan re-checks the tier with CURRENT patterns. Pins:
#   • a now-detectable secret shape in an archived copy is flagged by sid8 + pattern CLASS only —
#     the matched text never appears in the result;
#   • a properly-redacted (masked) copy is clean — masks are idempotent and re-match nothing;
#   • the (hash, engine-version) cache short-circuits unchanged files and re-scans on content change.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# is never read or written. Secret shapes are built at runtime — no credential-shaped literals.
import gzip, json, os, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="ss_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("ss_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_ss", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_ss", _loader))
_loader.exec_module(wiki)

W = _mkdtemp("ss_wiki_")
(W / "transcripts").mkdir(parents=True)
(W / "state").mkdir()
wiki.WIKI = W

secret = "AKIA" + "C" * 16                    # runtime-built AWS-key shape
sid = "feed0123-0000-4000-8000-000000000000"
dirty = W / "transcripts" / ("%s.jsonl.gz" % sid)
dirty.write_bytes(gzip.compress(('{"text":"leaked %s here"}\n' % secret).encode()))
clean = W / "transcripts" / "beef4567-0000-4000-8000-000000000000.jsonl.gz"
clean.write_bytes(gzip.compress(wiki._redact_secrets('{"text":"key %s ok"}\n' % secret).encode()))

# 1. Dirty copy flagged by class, clean (masked) copy is not; matched text never in the result.
total, flagged = wiki._scrub_scan()
assert total == 2, total
assert list(flagged) == ["feed0123"], flagged
assert flagged["feed0123"] == ["aws_key_id"], flagged
assert secret not in json.dumps(flagged), "matched text must never appear in results"
print("ok 1: now-detectable shape flagged by sid8 + class; masked copy clean; no text leaks")

# 2. Cache: results stable on re-run; a content change re-scans (dirty file scrubbed → clean).
cache1 = json.loads((W / "state" / "scrub_scan.json").read_text())
assert set(cache1) == {dirty.name, clean.name}, cache1
assert wiki._scrub_scan() == (2, {"feed0123": ["aws_key_id"]}), "cached re-run must be stable"
dirty.write_bytes(gzip.compress(wiki._redact_secrets('{"text":"leaked %s here"}\n' % secret).encode()))
total, flagged = wiki._scrub_scan()
assert (total, flagged) == (2, {}), "re-redacted file must re-scan clean on hash change: %r" % (flagged,)
print("ok 2: cache stable across runs, hash change triggers re-scan")

print("PASS test_scrub_scan")
