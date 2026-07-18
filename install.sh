#!/usr/bin/env bash
# claude-wiki one-line installer: plugin install + memory init/restore.
#   curl -fsSL https://raw.githubusercontent.com/necatisozer/claude-wiki/v0.1.3/install.sh | bash
#   curl -fsSL … | bash -s -- owner/repo     # explicit memory repo (restore TARGET)
# Non-interactive by necessity (curl|bash has no usable stdin) → passes --yes to `wiki init`.
# For interactive confirms: download this file and run it directly.
set -euo pipefail
need() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found — install it first" >&2; exit 1; }; }
need claude; need git; need python3
# gh preflight — only the default (no-arg) path needs it: there `wiki init` derives the memory-repo
# slug from your GitHub identity (`gh api user`) and creates/attaches the private repo via gh. An
# explicit `owner/repo`/git-URL target skips that derivation, so don't demand gh when one is passed.
if [ "$#" -eq 0 ]; then
  need gh
  gh auth status >/dev/null 2>&1 || { echo "error: gh is not authenticated — run: gh auth login" >&2
    echo "       (or re-run with an explicit memory repo, e.g. install.sh owner/repo)" >&2; exit 1; }
fi
# Pinned release: the marketplace copy must be EXACTLY this version. A >= / monotonic gate is
# unsafe after the 0.1.0 fresh-root history reset — a stale pre-reset clone (1.x) beats 0.x
# numerically forever while its `git pull` (how `marketplace update` refreshes) permanently
# fails against the unrelated new history, so it would silently keep serving the old engine.
EXPECT="0.1.3"
MANIFEST="$HOME/.claude/plugins/marketplaces/claude-wiki/.claude-plugin/plugin.json"
mkt_version() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' "$MANIFEST" 2>/dev/null || true; }
claude plugin marketplace add necatisozer/claude-wiki >/dev/null 2>&1 || true
claude plugin marketplace update claude-wiki >/dev/null 2>&1 || true
if [ "$(mkt_version)" != "$EXPECT" ]; then
  # Stale/divergent marketplace clone (a pre-reset clone can never pull across the new root):
  # auto-recover by re-cloning from scratch. The hard gate is the exact-version re-check below.
  claude plugin marketplace remove claude-wiki >/dev/null 2>&1 || true
  claude plugin marketplace add necatisozer/claude-wiki >/dev/null 2>&1 || true
fi
GOT="$(mkt_version)"
if [ "$GOT" != "$EXPECT" ]; then
  { echo "error: marketplace copy is version '${GOT:-missing}' but this installer requires exactly $EXPECT."
    echo "       Refusing to run an unknown engine. To recover manually:"
    echo "         claude plugin marketplace remove claude-wiki"
    echo "         claude plugin marketplace add necatisozer/claude-wiki"
    echo "       then re-run this installer."; } >&2
  exit 1
fi
claude plugin install wiki@claude-wiki >/dev/null 2>&1 || true
LIST="$(claude plugin list 2>/dev/null || true)"
if ! printf '%s' "$LIST" | grep -q "wiki@claude-wiki"; then
  echo "error: plugin install failed — run: claude plugin install wiki@claude-wiki" >&2; exit 1
fi
# live-verified format (claude 2026-07): plugin line, then indented Version/Scope/Status lines —
# Status ("✔ enabled" / "✘ disabled") sits at +3, so the window must be -A3.
if printf '%s' "$LIST" | grep -A3 "wiki@claude-wiki" | grep -qi "disabled"; then
  echo "error: plugin installed but disabled — run: claude plugin enable wiki@claude-wiki" >&2; exit 1
fi
ENGINE="${WIKI_INSTALL_ENGINE:-$HOME/.claude/plugins/marketplaces/claude-wiki/bin/wiki}"
exec python3 "$ENGINE" init ${1:+"$1"} --yes
