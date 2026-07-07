# tests/test_scan_secrets.py — run: python3 tests/test_scan_secrets.py
import os, subprocess, sys, tempfile
from pathlib import Path
from sync_util import ROOT, ENGINE

# probes never touch a live wiki: point the engine at a throwaway WIKI_HOME
ENV = {**os.environ, "WIKI_HOME": tempfile.mkdtemp(prefix="wiki5_scan_")}

def probe(text):
    out = subprocess.run([sys.executable, ENGINE, "_scan-selftest"], input=text,
                         capture_output=True, text=True, env=ENV)
    return out.stdout.strip().splitlines(), out.returncode

# --- positives: EVERY fake credential is runtime-constructed (never a literal) ---
akia   = "AKIA" + "B" * 16
sk_ant = "sk-" + "ant-" + "x" * 24                       # hyphenated provider key
ghp    = "ghp_" + "a" * 36
pat    = "github_pat_" + "c" * 24
slack  = "xox" + "b-" + "1" * 12
pem    = "-----BEGIN " + "RSA " + "PRIVATE KEY" + "-----"
jwt    = "eyJ" + "h" * 12 + "." + "p" * 12 + "." + "s" * 8
unq    = "AWS_SECRET_ACCESS_KEY" + "=" + "k" * 40        # UNQUOTED assignment form
conn   = "postgres" + "://" + "user" + ":" + "p" * 14 + "@" + "db.host/x"
# --- WP1 ROW 1 broadened patterns: one positive per NEW pattern, all runtime-constructed ---
stripe_sk = "sk_" + "live_" + "a" * 24                    # Stripe secret key (live)
stripe_rk = "rk_" + "test_" + "B" * 20                    # Stripe restricted key (test)
gaip      = "AIza" + "Sy" + "b" * 33                      # Google API key (AIza + 35)
ya29      = "ya29." + "z" * 30                            # Google OAuth access token
hient     = "Ab1" * 12                                    # high-entropy: 36 chars, lower+UPPER+digit mix

for i, sample in enumerate([akia, sk_ant, ghp, pat, slack, pem, jwt, unq, conn,
                            stripe_sk, stripe_rk, gaip, ya29, hient]):
    lines, rc = probe("some text\n" + sample + "\nmore text")
    assert rc == 1 and lines, "positive %d must HIT: %r..." % (i, sample[:12])
    # masking: the full secret must never appear in output
    assert all(sample not in l for l in lines), "mask leak on positive %d" % i

# --- negatives: benign code + the regex sources themselves must not match ---
# hex/uuid/single-case values are runtime-constructed so the FILE stays clean under _selfscan.
git_sha = "abcdef12" * 5                                  # 40-char lowercase hex SHA → no UPPER → no high_entropy
uuidv4  = "-".join(["abcdef01", "abcd", "abcd", "abcd", "abcdef012345"])   # hex UUID → no UPPER
lowb64  = "abcdefghijklmnop" * 3                          # 48-char lowercase → no digit/UPPER mix
for benign in [
    "val skipToken = tokenizer.next()",                   # 'token' not in assignment shape
    "password prompt shown to the user",
    "sk-[A-Za-z0-9_\\-]{20,}",                            # a pattern SOURCE, not a credential
    "AKIA[0-9A-Z]{16}",
    "git push origin sha:refs/heads/main",
    "task-management-plugin-development",                 # kebab prose containing "...sk-..." (FP regression)
    "risk-assessment-of-the-migration-plan",               # "risk-" also ends in "sk-"
    git_sha,                                              # 40-hex git SHA MUST NOT trip high_entropy
    uuidv4,                                               # a UUID MUST NOT trip high_entropy
    lowb64,                                               # long single-case base64 MUST NOT trip high_entropy
    "risk_live_" + "a" * 20,                              # 'sk_live_<20>' inside 'risk_' → stripe lookbehind blocks it
]:
    lines, rc = probe(benign)
    assert rc == 0, "false positive on: %r → %s" % (benign, lines)

# --- the permanent self-scan: every authored tracked file in THIS repo must be clean ---
# (the live data repo is deliberately NOT scanned here — it doesn't exist on CI and its
#  LLM-emitted corpus is the PUSH gate's job; the plugin repo is 100% authored → full scan)
out = subprocess.run([sys.executable, ENGINE, "_selfscan", str(ROOT)],
                     capture_output=True, text=True, env=ENV)
assert out.returncode == 0, "authored-file secret hit in %s:\n%s" % (ROOT, out.stdout)
print("PASS test_scan_secrets")
