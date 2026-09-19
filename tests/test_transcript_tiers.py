# tests/test_transcript_tiers.py — run: python3 tests/test_transcript_tiers.py
#
# The archive tiers are READABLE, not write-only:
#   • _resolve_transcript: synced / local archive / raw store — the FRESHEST copy wins, tier order
#     breaking a tie, so a session whose original Claude Code deleted is still served from
#     state/transcripts/, and a synced copy frozen by the 95 MB cap cannot shadow a growing archive.
#   • _sidechain_copies: the read surface for archive_transcripts: "full" — live set from
#     _sidechain_paths (the one home for the layout), each row served from its archived copy when
#     there is one, plus archived copies whose source has since been deleted.
#   • _dangling_sources: a deleted original that an archive tier still holds counts as ARCHIVED,
#     not dangling — counting it as lost made the archive settings look inert.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden BEFORE import — the live wiki
# is never read or written. No credential-shaped literals.
import os, sys, gzip, tempfile, shutil, atexit
import importlib.machinery, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "wiki"

_TMP = []
def _mkdtemp(prefix="tt_"):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return Path(d)
@atexit.register
def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)

_IMPORT_HOME = _mkdtemp("tt_import_")
os.environ["WIKI_HOME"] = str(_IMPORT_HOME)
_loader = importlib.machinery.SourceFileLoader("wiki_engine_tt", str(ENGINE))
wiki = importlib.util.module_from_spec(importlib.util.spec_from_loader("wiki_engine_tt", _loader))
_loader.exec_module(wiki)

W = _mkdtemp("tt_wiki_")
P = _mkdtemp("tt_projects_")
wiki.WIKI = W
wiki.PROJECTS = P

SID = "abcd1234-0000-0000-0000-00000000beef"
BODY = b'{"type":"user","message":"hello"}\n'

def gz(path, data=BODY):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(data)

fails = []
def check(label, cond):
    print("%s %s" % ("ok  " if cond else "FAIL", label))
    if not cond:
        fails.append(label)

# =============================================================================================
# 1. Tier order and fallthrough. The middle tier is the whole point: without it a deleted
#    original resolves to nothing even though state/transcripts/ holds a copy.
# =============================================================================================
check("no tiers -> no candidates", wiki._resolve_transcript("abcd1234") == ([], False, ""))

raw = P / "proj" / ("%s.jsonl" % SID)
raw.parent.mkdir(parents=True, exist_ok=True)
raw.write_bytes(BODY)
cands, is_gz, tier = wiki._resolve_transcript("abcd1234")
check("raw store alone resolves", (len(cands), is_gz, tier) == (1, False, "raw"))

gz(W / "state" / "transcripts" / ("%s.jsonl.gz" % SID))
cands, is_gz, tier = wiki._resolve_transcript("abcd1234")
check("local archive outranks raw store", (len(cands), is_gz, tier) == (1, True, "archive"))

gz(W / "transcripts" / ("%s.jsonl.gz" % SID))
cands, is_gz, tier = wiki._resolve_transcript("abcd1234")
check("synced outranks both", (len(cands), is_gz, tier) == (1, True, "synced"))

raw.unlink()                                          # cleanupPeriodDays deletes the original
(W / "transcripts" / ("%s.jsonl.gz" % SID)).unlink()  # this device never synced
cands, _, tier = wiki._resolve_transcript("abcd1234")
check("deleted original still served from the archive", (len(cands), tier) == (1, "archive"))

# A session past sync_transcripts' 95 MB cap stops being uploaded while the local archive keeps
# growing. First-tier-wins would serve the stale synced copy forever; freshest-wins must not.
gz(W / "transcripts" / ("%s.jsonl.gz" % SID), b"OLD TRUNCATED\n")
os.utime(W / "transcripts" / ("%s.jsonl.gz" % SID), (1, 1))
cands, _, tier = wiki._resolve_transcript("abcd1234")
check("a stale synced copy does not shadow a newer archive", tier == "archive")
os.utime(W / "transcripts" / ("%s.jsonl.gz" % SID), None)      # freshly synced again
cands, _, tier = wiki._resolve_transcript("abcd1234")
check("the fresh synced copy wins the common case", tier == "synced")

# =============================================================================================
# 2. Sidechain read surface: archive first, raw store second, deduped by name.
# =============================================================================================
check("no sidechains -> empty", wiki._sidechain_copies(SID) == [])

gz(W / "state" / "agent-transcripts" / SID / "agent-aaaa.jsonl.gz")
live = P / "proj" / SID / "subagents" / "agent-bbbb.jsonl"
live.parent.mkdir(parents=True, exist_ok=True)
live.write_bytes(BODY)
dupe = P / "proj" / SID / "subagents" / "agent-aaaa.jsonl"      # same name as the archived one
dupe.write_bytes(BODY)

copies = wiki._sidechain_copies(SID)
check("both sidechains listed", sorted(n for n, _, _, _ in copies) == ["agent-aaaa", "agent-bbbb"])
by_name = {n: (gzf, where) for n, _, gzf, where in copies}
check("archived copy wins over the live duplicate", by_name["agent-aaaa"] == (True, "archive"))
check("live-only sidechain still listed", by_name["agent-bbbb"] == (False, "raw"))

# Both sides now walk via _sidechain_paths, so agreement with the journal's subagents: count is
# structural rather than coincidental. Kept as a regression guard: the cost of re-forking that
# glob is a count that silently disagrees with what was archived, which is what this pins.
nested = P / "proj" / SID / "nested"
nested.mkdir(parents=True, exist_ok=True)
(nested / "agent-aaaa.jsonl").write_bytes(BODY)
live_count = len(wiki._sidechain_paths(P / "proj" / ("%s.jsonl" % SID), SID))
check("listing count matches the journal's subagent count",
      len(wiki._sidechain_copies(SID)) == live_count)

# Sizes must be comparable across tiers: a gzip size beside a plain one reads as a truncated copy.
big = b'{"type":"user","message":"padding"}\n' * 400
gz(W / "state" / "agent-transcripts" / SID / "agent-cccc.jsonl.gz", big)
check("archived size is reported uncompressed",
      wiki._original_size(W / "state" / "agent-transcripts" / SID / "agent-cccc.jsonl.gz", True) == len(big))

# =============================================================================================
# 3. _dangling_sources: archived ≠ dangling. This is the number a user turns the setting on to
#    move, so counting a rescued session as lost is the bug worth pinning.
# =============================================================================================
def journal(name, src):
    p = W / "journal" / "2026" / "09" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\ntitle: t\nsource: %s\n---\n\nbody\n" % src)

journal("a.md", str(P / "proj" / ("%s.jsonl" % SID)))              # deleted, but archived above
journal("b.md", str(P / "proj" / "11111111-2222-3333-4444-555555555555.jsonl"))   # gone entirely
still_here = P / "proj" / "99999999-2222-3333-4444-555555555555.jsonl"
still_here.write_bytes(BODY)
journal("c.md", str(still_here))

tot, gone, archived = wiki._dangling_sources()
check("total counts every journal source", tot == 3)
check("only the unarchived one is dangling", gone == 1)
check("the archived one is counted as archived", archived == 1)

# A raw-store hit under a different project dir means the original merely MOVED (a renamed cwd
# re-encodes the directory). That is neither dangling nor evidence that archiving did anything.
moved_sid = "77777777-2222-3333-4444-555555555555"
journal("d.md", str(P / "gone-proj" / ("%s.jsonl" % moved_sid)))
elsewhere = P / "renamed-proj" / ("%s.jsonl" % moved_sid)
elsewhere.parent.mkdir(parents=True, exist_ok=True)
elsewhere.write_bytes(BODY)
tot2, gone2, archived2 = wiki._dangling_sources()
check("a moved original is neither dangling nor archived",
      (tot2, gone2, archived2) == (tot + 1, gone, archived))

print("\n%s" % ("FAILED: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
