---
description: Session-wiki commands (query, status, ingest, lint, doctor, reindex)
---
Run `${CLAUDE_PLUGIN_ROOT}/bin/wiki $ARGUMENTS` via Bash and report the output to the user.

Common subcommands:
- `query "<terms>"` — FTS5 keyword search over the wiki (pages + journal)
- `status` — ledger + health summary
- `ingest` / `ingest --accept` / `ingest --reject` — review-gated fold of journal → pages
- `lint` — full-wiki health sweep → lint-report.md
- `doctor` — dependency + data-repo health check
- `reindex` — rebuild the ledger from the journal
