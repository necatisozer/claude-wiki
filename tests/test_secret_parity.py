# tests/test_secret_parity.py — WP1 "secret-gate + sync parity" (run: python3 tests/test_secret_parity.py)
#
# Covers the two WP1 rows end to end:
#   (1) ROW 1(a) cleaner-stage redactor — clean_transcript MASKS a secret in its OUTPUT before any
#       LLM prompt is built, so haiku/sonnet never receive a raw credential.
#   (2) ROW 2 sync-boundary parity — a pulled page/journal carrying a secret-shaped string, or a
#       forged `ingested: true` marker trying to skip validation, is REFUSED at the post-pull seam
#       (_post_pull_validate) and reset out of the live tree, never merged.
#   (3) ROW 1(d) no reporting path emits a raw match — a write that trips the push gate produces an
#       on-disk banner + wiki.log that show only the MASKED form.
#
# Every fake credential is runtime-constructed by concatenation (never a literal), so this file stays
# clean under `_selfscan`. All state is throwaway tempdirs with HOME + WIKI_HOME overridden.
import os, sys, json, tempfile, subprocess, importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from sync_util import (ENGINE, make_wiki, make_origin, wire_origin, enable_sync, run, sh, commit_file)

# ---- isolate: no live wiki is ever read/written — throwaway HOME/WIKI_HOME for the in-process import
os.environ["HOME"] = tempfile.mkdtemp(prefix="wiki5_parity_home_")
os.environ["WIKI_HOME"] = tempfile.mkdtemp(prefix="wiki5_parity_wiki_")
_loader = SourceFileLoader("wiki_engine_parity", ENGINE)
_spec = importlib.util.spec_from_loader("wiki_engine_parity", _loader)
wiki = importlib.util.module_from_spec(_spec); _loader.exec_module(wiki)


def _clone(origin):
    dest = Path(tempfile.mkdtemp(prefix="wiki5_parity_clone_")) / "c"
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True)
    sh(dest, "git", "config", "user.email", "t@t"); sh(dest, "git", "config", "user.name", "t")
    return dest


def _wire_and_seed():
    """A synced wiki + a bare origin holding its seed commit (server_sha established)."""
    w, o = make_wiki(), make_origin()
    wire_origin(w, o); enable_sync(w)
    r = run(["_push"], w)
    assert r.returncode == 0, "seed push failed: " + r.stdout + r.stderr
    return w, o


# =============================================================================================
# (1) cleaner-stage redactor: clean_transcript masks a secret BEFORE the prompt is built
# =============================================================================================
secret = "sk_" + "live_" + "d" * 24                       # runtime-constructed Stripe key (never a literal)
assert wiki.scan_secrets(secret), "sanity: the fake must be secret-shaped"
tdir = Path(tempfile.mkdtemp(prefix="wiki5_parity_tx_"))
tp = tdir / "sess.jsonl"
tp.write_text(json.dumps({
    "type": "user", "sessionId": "PARITY1", "cwd": "/tmp/proj",
    "timestamp": "2026-07-07T00:00:00Z",
    "message": {"role": "user", "content": "debug: my api key is " + secret + " please"}}) + "\n")
_h, cleaned, _s = wiki.clean_transcript(tp)
assert secret not in cleaned, "cleaner-stage redactor must mask the raw secret before any LLM sees it"
assert "sk_l" in cleaned and "…" in cleaned, "masked evidence must survive: %r" % cleaned[:200]
# direct redactor: masks + is idempotent (a masked span re-matches no pattern)
red = wiki._redact_secrets("k=" + secret)
assert secret not in red and wiki._redact_secrets(red) == red, "redactor must mask AND be idempotent"
print("ok 1: cleaner-stage redactor masks the secret before prompt build")

# =============================================================================================
# (2a) a pulled PAGE carrying a secret is refused at the post-pull seam, not merged live
# =============================================================================================
w, o = _wire_and_seed()
clone = _clone(o)
page_secret = "AIza" + "Sy" + "e" * 33                    # runtime-constructed Google API key
(clone / "pages" / "topics").mkdir(parents=True, exist_ok=True)
(clone / "pages" / "topics" / "leak.md").write_text(
    "---\nname: Leak\n---\nconfig value " + page_secret + " here\n")
sh(clone, "git", "add", "-A"); sh(clone, "git", "commit", "-q", "-m", "poison-page")
assert sh(clone, "git", "push", "-q", "origin", "main").returncode == 0
r = run(["_pull-selftest"], w)
assert "PULL-SOFT-FAIL" in r.stdout, "secret-bearing pull must be refused: " + r.stdout + r.stderr
assert not (w / "pages" / "topics" / "leak.md").exists(), "poisoned page must NOT be merged into the live tree"
pf = (w / "state" / "pull_failed")
assert pf.exists() and "secret:" in pf.read_text(), "pull_failed must record the secret refusal"
assert page_secret not in pf.read_text(), "pull_failed reason must not leak the raw secret"
print("ok 2a: pulled page carrying a secret is refused at the post-pull seam")

# =============================================================================================
# (2b) a forged `ingested: true` marker buys NO skip — journal is still scanned + refused
# =============================================================================================
w, o = _wire_and_seed()
clone = _clone(o)
journal_secret = "ya29." + "f" * 30                       # runtime-constructed Google OAuth token
jdir = clone / "journal" / "2026" / "07"; jdir.mkdir(parents=True, exist_ok=True)
(jdir / "2026-07-07__poison__deadbeef.md").write_text(
    "---\nname: Poison\nsessionId: FORGED1\ndate: 2026-07-07\n"
    "ingested: true\n---\n# Poison\n\ntoken " + journal_secret + " leaked\n")     # forged already-ingested
sh(clone, "git", "add", "-A"); sh(clone, "git", "commit", "-q", "-m", "forged-ingested")
assert sh(clone, "git", "push", "-q", "origin", "main").returncode == 0
r = run(["_pull-selftest"], w)
assert "PULL-SOFT-FAIL" in r.stdout, "forged `ingested:` must NOT exempt the secret scan: " + r.stdout + r.stderr
merged = w / "journal" / "2026" / "07" / "2026-07-07__poison__deadbeef.md"
assert not merged.exists(), "poisoned journal must NOT be merged despite ingested:true"
print("ok 2b: forged `ingested: true` marker buys no skip past the secret gate")

# =============================================================================================
# (3) no reporting path emits a raw match: push-gate banner + wiki.log show only the masked form
# =============================================================================================
w, o = _wire_and_seed()
raw_key = "AKIA" + "C" * 16                                # runtime-constructed AWS key id
commit_file(w, "pages/topics/report.md",
            "---\nname: Report\n---\naccess key " + raw_key + " committed\n", "poison-local")
r = run(["_push"], w)
assert r.returncode == 1, "push gate must BLOCK a committed secret: rc=%s\n%s" % (r.returncode, r.stdout + r.stderr)
banner = (w / "state" / "push_blocked").read_text()
assert "aws_key_id" in banner and "(len" in banner, "banner must name the pattern + masked form:\n" + banner
assert raw_key not in banner, "push_blocked banner leaked the RAW secret"
logtext = (w / "logs" / "wiki.log").read_text()
assert "BLOCK" in logtext.upper(), "wiki.log must record the block"
assert raw_key not in logtext, "wiki.log leaked the RAW secret"
print("ok 3: push-gate banner + wiki.log show only the masked form")

print("PASS test_secret_parity")
