# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-07

First public release. Version numbers below 0.1.0 do not exist; prior 1.x
versions were private development builds on a discarded history — the public
version line starts here. Semver 0.x signals pre-stable: 1.0.0 is reserved for
a later stability milestone.

### Added

- **Session capture** — a Stop-hook records each Claude Code session; a
  classifier gates what is worth remembering into an append-only journal.
- **Two-phase ingest** — journal entries are distilled into durable, topical
  wiki pages; every write is stage-then-promote with a deterministic risk gate
  (suspicious updates are held for review, never auto-applied).
- **Recall** — a SessionStart digest surfaces relevant memory at session start;
  `wiki query` (SQLite FTS5 keyword search) plus plain `Read` serve on-demand
  lookup. No MCP server, no embeddings — markdown files are the source of truth.
- **Security hardening** — untrusted transcript/journal/page text is delimited
  at every LLM boundary; symlink-free staged writes; secret scanning and
  redaction on capture, write, and push; transport allowlist for `wiki init`;
  pulled content passes the same gates as local writes (sync-boundary parity).
- **Derived identity** — the memory-repo slug and git identity are derived from
  the running user's environment at init; no author identity is baked in.
- **Doctor & lint** — `wiki doctor` validates config, state, and sync health;
  `wiki lint` checks corpus integrity.
- POSIX-only engine, Python 3 stdlib only; one-line `install.sh` installer
  pinned to this release.
