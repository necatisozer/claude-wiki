# tests/test_journal_retention.py — run: python3 tests/test_journal_retention.py
#
# WP3 "journal retention" (S3, P2). Pins the decided `maintain` retention semantics:
#   ARCHIVE, NEVER DELETE — ingested journal entries older than journal.archive_after_days are MOVED
#   into journal/archive/ (still on disk, in git, synced) and the HOT read path skips the archive.
#
#   A. ARCHIVE OLD INGESTED  — an ingested entry older than the threshold is MOVED into journal/archive/
#                              (its content survives there); a recent entry stays hot; an OLD but
#                              UN-INGESTED entry stays hot (its decisions aren't folded into pages yet).
#   B. HOT PATH SKIPS ARCHIVE — after archiving, `wiki query` (FTS) and the SessionStart digest do NOT
#                              surface an archived entry; a recent entry still does; the archive is still
#                              reachable on explicit `wiki query --include-archive`.
#   C. DISABLED (0) = NO-OP  — archive_after_days: 0 archives nothing.
#   D. IDEMPOTENT            — a second maintain re-archives nothing and never errors or double-moves.
#   E. YOUNG-ONLY = NO-OP    — a journal with only recent entries is untouched (no archive/ created).
#
# SAFETY: every byte of state lives in tempfile.mkdtemp() dirs (via sync_util's throwaway git wikis);
# the live wiki (~/.claude/wiki) and ~/.claude/settings*.json are never read or written. No
# credential-shaped literal appears here (distinctive tokens are plain invented words).
import json, sqlite3, os, tempfile
from datetime import datetime, timezone, timedelta
# `maintain` now runs the WP4 reconcile catch-up, which enumerates ~/.claude/projects (= $HOME/.claude/
# projects). Override HOME to an EMPTY throwaway so this test's maintain never reads the real user's
# transcripts (safety) and reconcile finds nothing — maintain then exercises only the retention pass.
os.environ["HOME"] = tempfile.mkdtemp(prefix="jr_home_")
from sync_util import make_wiki, run, sh

NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=200)      # well past the 90d default threshold
REC = NOW - timedelta(days=3)        # comfortably young

# distinctive, non-secret-shaped tokens — one per entry, in BOTH the journal body (FTS) and the
# ledger description (digest recents), so we can prove presence/absence on each surface.
TOK_OLD = "archaeopteryxarchivedtoken"
TOK_REC = "quetzalcoatlrecenttoken"
TOK_PEND = "pterodactylpendingtoken"

_SCHEMA = """CREATE TABLE IF NOT EXISTS sessions(
    session_id TEXT PRIMARY KEY, project TEXT, transcript_path TEXT, first_seen TEXT,
    message_count INTEGER, last_mtime INTEGER, summarized_at TEXT, summarized_by TEXT,
    page_path TEXT, ingested_at TEXT, ingested_by TEXT, status TEXT, skip_reason TEXT,
    date TEXT, title TEXT, description TEXT)"""


def journal_rel(when, sid):
    return "journal/%s/%s.md" % (when.strftime("%Y/%m"), sid)


def write_entry(wiki, when, ingested, sid, token):
    """Write a per-session journal file with real frontmatter (date/ended/ingested/sessionId)."""
    rel = journal_rel(when, sid)
    p = wiki / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\nname: Session %s\ndescription: %s\ntype: session\nsessionId: %s\n"
        "date: %s\nended: %sT00:00:00Z\ningested: %s\n---\n\n# Session %s\n\n%s body line\n"
        % (sid, token, sid, when.strftime("%Y-%m-%d"), when.strftime("%Y-%m-%d"),
           "true" if ingested else "false", sid, token))
    return rel


def seed_ledger(wiki, rows):
    """Seed the ledger (a rebuildable local cache) so the digest has recents to recall. Each row:
    (sid, date, page_path, desc, ingested_at)."""
    (wiki / "state").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(wiki / "state" / "ledger.db"))
    conn.execute(_SCHEMA)
    for sid, date, page, desc, ing in rows:
        conn.execute(
            "INSERT OR REPLACE INTO sessions "
            "(session_id,project,summarized_at,page_path,date,title,description,ingested_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sid, "proj", "2026-07-06T00:00:00", page, date, "T", desc, ing))
    conn.commit(); conn.close()


def new_wiki(archive_after_days=90):
    """A throwaway wiki with retention configured and NO ingest/lint cron (so `maintain` runs only the
    retention pass — no LLM, no network)."""
    w = make_wiki()
    (w / "config.json").write_text(
        '{"enabled": true, "digest": {"max_chars": 50000}, "journal": {"archive_after_days": %d}}'
        % archive_after_days)
    return w


def archived_rel(when, sid):
    return "journal/archive/%s/%s.md" % (when.strftime("%Y/%m"), sid)


def qpaths(w, *args):
    return [h["path"] for h in json.loads(run(["query", *args, "--json"], w).stdout)]


# =============================================================================================
# A + B + D — the full scenario on one wiki: archive the old ingested entry, keep the rest hot,
#             prove the hot path skips the archive, then prove a second run is idempotent.
# =============================================================================================
w = new_wiki(90)
write_entry(w, OLD, True,  "oldsess",    TOK_OLD)    # old + ingested   → ARCHIVED
write_entry(w, REC, True,  "recentsess", TOK_REC)    # recent + ingested → stays hot
write_entry(w, OLD, False, "pendold",    TOK_PEND)   # old + UN-ingested → stays hot (not folded yet)
seed_ledger(w, [
    ("oldsess",    OLD.strftime("%Y-%m-%d"), journal_rel(OLD, "oldsess"),    TOK_OLD, "2026-07-06T01:00:00"),
    ("recentsess", REC.strftime("%Y-%m-%d"), journal_rel(REC, "recentsess"), TOK_REC, "2026-07-06T01:00:00"),
])
sh(w, "git", "add", "-A"); sh(w, "git", "commit", "-q", "-m", "seed journal")

# sanity: before retention the old entry IS in the hot search index
assert any(p.endswith("oldsess.md") for p in qpaths(w, TOK_OLD)), "old entry should be hot before maintain"

r = run(["maintain"], w)
assert r.returncode == 0, r.stderr
assert "archived 1 journal entry older than 90d" in r.stdout, "maintain must report what it did: %r" % r.stdout

# --- A: the MOVE happened; nothing was deleted; the recent + old-un-ingested entries stayed ---
assert (w / archived_rel(OLD, "oldsess")).exists(), "old ingested entry must be MOVED into journal/archive/"
assert not (w / journal_rel(OLD, "oldsess")).exists(), "old entry must be gone from the hot journal path"
assert TOK_OLD in (w / archived_rel(OLD, "oldsess")).read_text(), "archived content must survive (never deleted)"
assert (w / journal_rel(REC, "recentsess")).exists(), "a recent entry must stay in journal/"
assert (w / journal_rel(OLD, "pendold")).exists(), "an OLD but UN-ingested entry must NOT be archived"
print("ok A: old ingested entry archived (moved, not deleted); recent + un-ingested stay hot")

# --- B: hot path skips the archive; archive still reachable on explicit --include-archive ---
assert not any("archive" in p for p in qpaths(w, TOK_OLD)), "archived entry must NOT surface in hot `wiki query`"
assert qpaths(w, TOK_OLD) == [], "no hot hit at all for an archived-only token"
assert any(p.endswith("recentsess.md") for p in qpaths(w, TOK_REC)), "a recent entry must still be searchable"
inc = qpaths(w, TOK_OLD, "--include-archive")
assert any(p == archived_rel(OLD, "oldsess") for p in inc), "--include-archive must still reach the archive: %r" % inc
dg = run(["digest", "--cwd", str(w)], w).stdout
assert TOK_OLD not in dg, "the digest recents must NOT surface an archived entry"
assert TOK_REC in dg, "the digest recents must still surface a recent entry"
print("ok B: hot query + digest skip the archive; `wiki query --include-archive` still reaches it")

# --- D: idempotent — a second maintain re-archives nothing, errors nothing, moves nothing twice ---
r2 = run(["maintain"], w)
assert r2.returncode == 0, r2.stderr
assert "archived" not in r2.stdout, "a re-run must archive nothing (idempotent): %r" % r2.stdout
assert (w / archived_rel(OLD, "oldsess")).exists(), "the archived entry must remain exactly where it is"
assert not (w / journal_rel(OLD, "oldsess")).exists(), "no resurrection into the hot path"
print("ok D: re-running maintain is idempotent (no double-archive, no error)")

# =============================================================================================
# C — DISABLED (archive_after_days: 0) is a no-op: even an ancient ingested entry stays hot.
# =============================================================================================
wc = new_wiki(0)
write_entry(wc, OLD, True, "ancient", TOK_OLD)
sh(wc, "git", "add", "-A"); sh(wc, "git", "commit", "-q", "-m", "seed")
rc = run(["maintain"], wc)
assert rc.returncode == 0, rc.stderr
assert "archived" not in rc.stdout, "disabled retention must report no archiving"
assert (wc / journal_rel(OLD, "ancient")).exists(), "with archive_after_days:0 an old entry must stay hot"
assert not (wc / "journal" / "archive").exists(), "disabled retention must not create an archive dir"
print("ok C: archive_after_days:0 disables retention (no-op)")

# =============================================================================================
# E — YOUNG-ONLY journal is untouched (nothing crosses the threshold; no archive/ created).
# =============================================================================================
we = new_wiki(90)
write_entry(we, REC, True, "fresh1", TOK_REC)
write_entry(we, NOW - timedelta(days=10), True, "fresh2", "gingkoyoungtoken")
sh(we, "git", "add", "-A"); sh(we, "git", "commit", "-q", "-m", "seed")
re_ = run(["maintain"], we)
assert re_.returncode == 0, re_.stderr
assert "archived" not in re_.stdout, "a young-only journal must archive nothing"
assert not (we / "journal" / "archive").exists(), "a young-only journal must not create an archive dir"
assert (we / journal_rel(REC, "fresh1")).exists(), "young entries stay exactly where they are"
print("ok E: a young-only journal is untouched")

print("PASS test_journal_retention")
