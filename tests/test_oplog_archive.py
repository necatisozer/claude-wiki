# tests/test_oplog_archive.py — run: python3 tests/test_oplog_archive.py
#
# Two durability surfaces added together:
#   • _oplog: log.md is the durable, unix-parseable chronological record (ledger = machine-only
#     sqlite; logs/wiki.log rotates away). Header seeded once; one appended line per op; a symlink
#     at log.md is refused (O_NOFOLLOW via _safe_append), and a failure never raises.
#   • _archive_transcript: OPT-IN (record.archive_transcripts) gzip copy of the raw transcript
#     into the untracked state/transcripts/ — off by default, byte-faithful when on, overwrites on
#     re-record (append-only transcripts: newer is a superset), and never raises on a bad source.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# is never read or written. No credential-shaped literals.
import gzip, os, sys, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="oa_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("oa_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_oa", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_oa", _loader))
_loader.exec_module(wiki)

W = _mkdtemp("oa_wiki_")
(W / "state").mkdir(parents=True)
wiki.WIKI = W

# =============================================================================================
# 1. _oplog: header seeded exactly once; lines append in order; format is `- <iso> · kind · detail`.
# =============================================================================================
wiki._oplog("record", "cafe0123 journal/2026/08/x.md")
wiki._oplog("ingest", "3 session(s) → metro-di")
text = (W / "log.md").read_text()
lines = [l for l in text.splitlines() if l.startswith("- ")]
assert text.startswith("# Operations log") and text.count("# Operations log") == 1, "header seeded once"
assert len(lines) == 2 and lines[0].endswith("· record · cafe0123 journal/2026/08/x.md"), lines
assert lines[1].endswith("· ingest · 3 session(s) → metro-di"), lines
assert " · " in lines[0] and lines[0][2:22].strip(), "iso timestamp prefix present"
print("ok 1: log.md seeded once, appends in order, parseable format")

# =============================================================================================
# 2. _oplog never raises and never follows a symlink at log.md.
# =============================================================================================
victim = _mkdtemp("oa_victim_") / "victim.md"
victim.write_text("untouched\n")
(W / "log.md").unlink()
os.symlink(victim, W / "log.md")
wiki._oplog("record", "attacker line")            # O_NOFOLLOW → refused; must not raise
assert victim.read_text() == "untouched\n", "symlinked log.md must never redirect the write"
os.unlink(W / "log.md")
print("ok 2: symlinked log.md refused, no exception escapes")

# =============================================================================================
# 3. _archive_transcript: off by default; on → byte-faithful gzip in state/transcripts/;
#    re-record overwrites; a missing source never raises.
# =============================================================================================
sid = "cafe0123-0000-4000-8000-000000000000"
src = _mkdtemp("oa_tr_") / "t.jsonl"
src.write_bytes(b'{"type":"user"}\n' * 100)
dst = W / "state" / "transcripts" / ("%s.jsonl.gz" % sid)

wiki._archive_transcript(str(src), sid, {})                                        # default: off
assert not dst.exists(), "archive must be OPT-IN"
on = {"record": {"archive_transcripts": True}}
wiki._archive_transcript(str(src), sid, on)
assert gzip.decompress(dst.read_bytes()) == src.read_bytes(), "archive must be byte-faithful"
src.write_bytes(src.read_bytes() + b'{"type":"assistant"}\n')                      # transcript grew
wiki._archive_transcript(str(src), sid, on)
assert gzip.decompress(dst.read_bytes()) == src.read_bytes(), "re-record must refresh the archive"
wiki._archive_transcript(str(src) + ".missing", sid, on)                           # must not raise
print("ok 3: opt-in gating, byte-faithful round-trip, overwrite on growth, bad source tolerated")

# =============================================================================================
# 4. _sync_transcript: off by default; on → TRACKED transcripts/<sid>.jsonl.gz whose content is
#    secret-REDACTED (the whole point — nothing lands unredacted in the synced repo).
# =============================================================================================
secret = "AKIA" + "B" * 16                    # built at runtime — no credential-shaped literal
src2 = _mkdtemp("oa_tr2_") / "t.jsonl"
src2.write_text('{"text":"key is %s here"}\n{"text":"plain line"}\n' % secret)
sdst = W / "transcripts" / ("%s.jsonl.gz" % sid)

wiki._sync_transcript(str(src2), sid, {})                                          # default: off
assert not sdst.exists(), "synced copy must be OPT-IN"
wiki._sync_transcript(str(src2), sid, {"record": {"sync_transcripts": True}})
out = gzip.decompress(sdst.read_bytes()).decode()
assert secret not in out, "secret must be redacted before the tracked copy lands"
assert "plain line" in out and "(len" in out, "non-secret content kept, mask marker present"
wiki._sync_transcript(str(src2) + ".missing", sid, {"record": {"sync_transcripts": True}})
print("ok 4: synced copy opt-in, redacted, non-secret content intact, bad source tolerated")

print("PASS test_oplog_archive")
