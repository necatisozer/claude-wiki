---
description: Session-wiki commands (query, status, ingest, lint, doctor, reindex)
---
Run `~/.claude/plugins/marketplaces/claude-wiki/bin/wiki $ARGUMENTS` via Bash and report the output to the user.
(That path matches the plugin's shipped permission allow-rules, so recall runs prompt-free. Only if it does not exist — e.g. a dev checkout installed outside the marketplace — fall back to `${CLAUDE_PLUGIN_ROOT}/bin/wiki $ARGUMENTS`.)

Common subcommands:
- `query "<terms>"` — FTS5 keyword search over the wiki pages (`--include-journal` adds per-session notes)
- `status` — ledger + health summary
- `ingest` / `ingest --accept` / `ingest --reject` — review-gated fold of journal → pages
- `lint` — full-wiki health sweep → lint-report.md
- `doctor` — dependency + data-repo health check
- `reindex` — rebuild the ledger from the journal
