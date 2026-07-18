# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-07-18

Patch release: keep the schema's hard-contradiction promise, and fix four
documentation inaccuracies surfaced by a two-agent audit of the shipped tree
against its original design (Karpathy's LLM-wiki gist).

### Changed

- **`hard_contradiction:` is now honored fail-closed.** SCHEMA.md rule 5 has
  always promised that a model-reported hard contradiction is "held for review,
  not auto-committed" — but the engine ignored the field entirely, so a hard
  contradiction that stayed under the diff cap with clean shapes auto-committed.
  The gate now treats any non-`none` `hard_contradiction:` line as an
  *additional* hold reason. Trust is strictly one-directional: the field can add
  a hold, never clear one — an injection that blanks it changes nothing, because
  every deterministic check still runs — and a decoy `none` line planted in a
  page body cannot mask a real one. The hold reason stays content-free.

### Fixed

- ARCHITECTURE.md's divergences list now documents two real departures it was
  missing: the schema is a fixed shipped contract (not per-user co-designed, a
  data-repo SCHEMA.md is ignored), and "sessions subsume notes" has a known
  edge (exploratory sessions collapse to one-line records).
- ARCHITECTURE.md's sync-boundary parity claim no longer overstates: pulled
  content passes the symlink/secret/size/UTF-8 gates; instruction-shaped text
  is neutralized by the digest sandbox rather than rejecting the pull.
- SCHEMA.md no longer calls journal retention "not yet automated" — `maintain`
  has archived ingested entries on a 90-day default since 0.1.0.

## [0.1.2] - 2026-07-18

Patch release: decouple the lint detection-net sensitivity from the security gate.

### Changed

- **Lint detection net is now high-precision, independent of the security gate.** The lint sweep
  previously reused the record/ingest classifier's deliberately fail-closed shape checks over the
  whole corpus, so ordinary developer notes flooded the report with false positives: every line
  saying "you"/"your" and every mention of the word "injection" (Dependency Injection, SQL/host
  injection) tripped the `injection` tag, and camelCase/underscore identifiers (Gradle task names,
  C linker symbols) tripped `secret` via the high-entropy catch-all. Lint now uses its own narrower
  detectors — `injection` flags only an actual instruction-override clause ("ignore/disregard/forget
  … previous/prior/above"), and `secret` flags only the named high-confidence credential patterns
  (not the high-entropy catch-all). `leak` is unchanged (already precise).
- **The security gate is untouched.** `record`, `ingest`, and the push scan remain fully fail-closed
  on bare second-person address, every imperative verb, and high-entropy runs — enforcement is
  unchanged; only the retrospective lint *report* got quieter.

### Fixed

- `test_install_sh.py` now derives the pinned version from `install.sh` instead of hardcoding it, so
  a release bump can't silently break the installer gate test again.

## [0.1.1] - 2026-07-18

Patch release: security hardening follow-up and a secret-scanner false-positive fix.

### Fixed

- **Write guard soundness** — closed a companion-split path that could write
  outside the data tree; the stage-then-promote write guard is now sound.
- **Secret-scanner false positive** — the high-entropy detector no longer flags
  long path segments that mix case and digits (e.g. the engine's own `source:`
  transcript path or a quoted `feature/…/SomeCard.kt`). A run beginning right
  after a `/` or `.` separator is a path segment, not a credential; real secrets
  are preceded by `=`, `:`, quote, whitespace, or start-of-line. Standalone
  high-entropy tokens are still detected. This unblocks legitimate session
  journals that quote file paths from being held at the push gate.

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

### Changed

- Marketplace renamed `necatisozer-wiki` → `claude-wiki` (2026-07-08, before any
  external installs; the `v0.1.0` tag was re-cut to include this). The install
  path is `~/.claude/plugins/marketplaces/claude-wiki/` and the plugin ID is
  `wiki@claude-wiki`.
