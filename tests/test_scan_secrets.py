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
# path SEGMENTS that mix case+digit and exceed 32 chars but sit after a '/' or '.' separator:
# the engine's own `source:` line and quoted code paths. A path is not a standalone credential.
src_line = "source: /Users/necatisozer/.claude/projects/-Users-necatisozer--claude-wiki-" + \
           "-".join(["950a4ee6", "5250", "400d", "ad4d", "e3417a75ec92"]) + "/sess.jsonl"
code_path = "modified `feature/generation/ui/GenerationCardMenu2State.kt`, added state"
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
    src_line,                                             # engine-written `source:` path slug MUST NOT trip high_entropy
    code_path,                                            # quoted code path segment MUST NOT trip high_entropy
    # --- v0.1.11: long code identifiers MUST NOT trip high_entropy. The first two are the exact
    # strings that fail-closed a real `init` restore (KMP journal entries); the rest are the same
    # shape from Gradle/Compose/Kotlin-Native naming. All satisfy lower+UPPER+digit at >=32 chars.
    "iOS linkPodDebugFrameworkIosSimulatorArm64: OK",
    "symbol kniprot_cocoapods_AmplitudeSwift0_NSPredicateValidating multiply defined",
    "ran assembleDebugAndroidTestSourcesJavaWithJavac",
    "observeAuthenticatedPaymentStateDataFlow emits twice",
    "collectAsStateWithLifecycle_rememberCoroutineScope",
    "bumped MARKETING_VERSION_CURRENT_PROJECT_VERSION_bump",
]:
    lines, rc = probe(benign)
    assert rc == 0, "false positive on: %r → %s" % (benign, lines)

# --- v0.1.11: the identifier exemption must NOT swallow real credentials. Every positive above
# already covers the named patterns; these are high_entropy-shaped blobs that are NOT word-like
# (digit-dense and/or no long alphabetic tokens) and so must still HIT.
for i, keyish in enumerate([
    "Ab1" * 12,                                           # 36 chars, 33% digits → not identifier-shaped
    "x7Kq" + "9Zm2Pv4Ln8Rt6Wy3Bc5Df1Gh0Jk" + "Qs2Vx",      # scattered digits, no 4+ word run
    "aB3" + "".join("cD%d" % d for d in range(10)) + "eF" + "gH" * 4,   # runtime-built, no literal run
]):
    lines, rc = probe("token = " + keyish)
    assert rc == 1 and lines, "high_entropy positive %d must still HIT: %r" % (i, keyish[:12])

# --- the permanent self-scan: every authored tracked file in THIS repo must be clean ---
# (the live data repo is deliberately NOT scanned here — it doesn't exist on CI and its
#  LLM-emitted corpus is the PUSH gate's job; the plugin repo is 100% authored → full scan)
out = subprocess.run([sys.executable, ENGINE, "_selfscan", str(ROOT)],
                     capture_output=True, text=True, env=ENV)
assert out.returncode == 0, "authored-file secret hit in %s:\n%s" % (ROOT, out.stdout)
print("PASS test_scan_secrets")
