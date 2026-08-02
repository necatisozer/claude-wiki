# tests/test_transcript_cmd.py — run: python3 tests/test_transcript_cmd.py
#
# `wiki transcript <sid8>` — the last hop of the page → journal → transcript verification chain.
# Pins:
#   • a unique sid8 prefix resolves and prints the CLEANED rendering (header + body);
#   • output is redacted on BOTH paths (cleaned + --raw) — a secret-shaped span never prints;
#   • an ambiguous prefix lists candidates and exits 2; no match exits 1; bad args exit 2.
#
# SAFETY: all state in tempfile.mkdtemp() dirs; WIKI_HOME overridden — the live wiki is never read
# or written. Secret shapes are built at runtime — no credential-shaped literals.
import gzip, json, os
from sync_util import make_wiki, run

secret = "AKIA" + "D" * 16
sid = "feed0123-0000-4000-8000-000000000000"

def entry(text, typ="user"):
    return json.dumps({"type": typ, "sessionId": sid, "timestamp": "2026-08-02T10:00:00Z",
                       "cwd": "/tmp/proj",
                       "message": {"role": typ, "content": [{"type": "text", "text": text}]}})

w = make_wiki()
(w / "transcripts").mkdir()
body = entry("please fix the flaky test") + "\n" + entry("key is %s do not tell" % secret, "assistant") + "\n"
(w / "transcripts" / ("%s.jsonl.gz" % sid)).write_bytes(gzip.compress(body.encode()))

# 1. Unique prefix → cleaned rendering, header + content, secret masked.
r = run(["transcript", "feed0123"], w)
assert r.returncode == 0, r.stderr
assert "sid: %s" % sid in r.stdout and "flaky test" in r.stdout, r.stdout
assert secret not in r.stdout and "(len" in r.stdout, "secret must be masked in cleaned output"
print("ok 1: cleaned rendering with header; secret masked")

# 2. --raw prints the stored JSONL shape, still redacted.
r = run(["transcript", "feed0123", "--raw"], w)
assert r.returncode == 0 and '"type"' in r.stdout, r.stdout
assert secret not in r.stdout, "secret must be masked in --raw output"
print("ok 2: --raw redacted")

# 3. Ambiguous prefix lists candidates (exit 2); no match exits 1; junk arg exits 2.
sid2 = "feed0999-0000-4000-8000-000000000000"
(w / "transcripts" / ("%s.jsonl.gz" % sid2)).write_bytes(gzip.compress(entry("x").encode()))
r = run(["transcript", "feed0"], w)
assert r.returncode == 2 and sid[:8] in r.stdout and sid2[:8] in r.stdout, r.stdout
assert run(["transcript", "beefbeef"], w).returncode == 1
assert run(["transcript", "../../etc"], w).returncode == 2
print("ok 3: ambiguity listed, no-match and bad-arg refused")

print("PASS test_transcript_cmd")
