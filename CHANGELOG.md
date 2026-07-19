# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.7] - 2026-07-19

Tuning release (companion to 0.1.6): retarget the record-stage reject classifier
the same way — the only gate that silently drops a session now drops far less.

### Changed

- **Record-stage injection reject is now override-clause-only.** The record
  classifier is the one gate that *silently drops* a session (fail-closed, never
  journaled). It previously rejected on the broad shape check (bare "you", any
  imperative verb, a URL), which dropped ~11% of sessions in production and would
  reject 20% of the already-kept corpus on replay — legitimate security-review
  work, unrecoverable. It now rejects for injection only on an unambiguous
  instruction-override clause ("ignore/disregard/forget … previous"), which has
  zero false positives on the real corpus. Replay: sessions dropped for injection
  falls from 68/330 to 0; 62 previously-lost sessions would be kept.
- **Ambiguous shapes are held, not dropped.** Imperative+URL, imperative+
  second-person, and `curl`/`wget`/`exfiltrate` are no longer a silent drop at
  record — they survive to the journal and are caught reviewably by the ingest
  risk gate's HOLD (a hold can be accepted; a drop cannot be undone). The one
  "hard" match the corpus produced was itself a false positive (a session that
  "verified fix via curl"), confirming those tokens are unsafe as a drop trigger.
- **Secret/PII and leak-shape (chain-of-thought / system-prompt / tool-transcript
  leakage) rejects are unchanged** — narrowing applies only to the injection tier.

The pipeline's three tiers are now coherent: silent-drop → override clause only;
reviewable-hold → attack tokens + injection combinations (0.1.6); keep → lone
imperatives / URLs / second-person prose.

## [0.1.6] - 2026-07-19

Tuning release: retarget the ingest risk gate from "hold on any single shape" to
"hold on injection-shaped combinations", so the gate stays a meaningful signal on
a corpus whose ordinary vocabulary overlaps the threat vocabulary.

### Changed

- **Ingest risk gate is now tiered.** The auto-accept hold previously fired on ANY
  single risky shape — one URL, one imperative verb, or a bare "you". On a corpus
  of security-review notes those saturate (measured: 57% of pages held), so the
  gate fired on nearly every batch and trained the reviewer to rubber-stamp — a
  signal that is always on carries no information. The gate now holds only on:
  a **hard** shape that stands alone (secret/PII, an instruction-override clause
  like "ignore previous …", or `curl`/`wget`/`exfiltrate`), or an
  **injection-shaped combination** (imperative + URL, or imperative + second-person
  address). A lone reference URL, a lone imperative verb (`delete`, `remove`, and —
  because this engine's own domain is media downloading — `fetch`/`download`), or a
  bare "you"/"your" in prose no longer holds. On the current corpus this drops
  held pages from 12/21 to 1/21, and the one that still holds is a genuine
  imperative+URL combination.
- **The secret/PII hold is unchanged and unconditional** — narrowing applies only
  to the instruction-shape tier, never to credential detection.
- **The record-stage reject classifier is unchanged.** It still uses the broad
  shape pattern (a fail-closed *reject*, not a *hold*), by design — reject→keep is
  a different risk decision than hold→review and is out of scope for this release.

## [0.1.5] - 2026-07-19

Security & integrity release: fixes for the findings of a 15-agent audit of the
pipeline. Each claim was re-verified against the code before fixing — two of the
audit's correctness claims (unbounded digest, concurrent re-record overwrite) did
not reproduce (the digest is hard-capped; re-record is already serialized under
`record.lock`) and are noted here as checked-not-fixed.

### Security

- **Sync-boundary shape gate now blocks hook injection.** A compromised remote
  could commit an executable file or a `.githooks/pre-push` into the memory repo;
  because the repo sets `core.hooksPath=.githooks`, that hook would execute on the
  engine's next git operation. The pull/restore shape gate now rejects any tracked
  executable (`100755`) blob and any tracked `.githooks/` path, alongside the
  existing symlink/submodule rejection.
- **`init --restore` now validates the remote tree.** Restore previously ran
  `git checkout` with no gate — the one path where a hostile remote's content
  reached disk unchecked. It now runs the shape gate (pre-checkout) and the same
  secret/size/UTF-8 content gates a pull clears; a failure drops `.git` and
  refuses, restoring nothing.

### Fixed

- **Ledger never advances past a failed commit.** Auto-ingest and `ingest
  --accept` now check the `git commit` result: on failure the ledger is left
  untouched (sessions stay un-ingested) so a batch can't be marked folded with
  nothing committed. The fold re-emits full page bodies, so a retry converges.
- **Companion (`<slug>-sources`) pages are fold-safe.** The oversized-page split
  now derives the companion path from the safe file-path stem, never the
  model-authored `slug:` (which a crafted value could have aimed at another page's
  companion); companions are excluded from the ingest selection index; and a
  model-emitted `<slug>-sources` FILE-block is refused. This closes the case where
  a fold deleted archived citations from a `-sources` page.
- **`maintain` re-checks the schema version after `sync --rebase`** — a pull can
  deliver a newer `config.json` from an upgraded device, which must not then be
  compiled against by the older engine.
- **Secret scanner** gains a Slack incoming-webhook pattern, covering the
  highest-value real-world case of a credential carried as a URL path segment
  (the residual class the high-entropy detector deliberately skips to avoid the
  path-false-positive regression).

## [0.1.4] - 2026-07-19

Patch release: two fixes born from live incidents — a stale-cache engine guard
and support for Claude Code's 2026-07 transcript-format additions.

### Added

- **Stale-cache engine guard.** Claude Code materializes the plugin into a
  version-keyed cache and a long-running process keeps executing the version it
  loaded at startup — so after an upgrade, hooks could silently run an OLD
  engine against current data (observed live: a stale 0.1.0 engine ran the
  weekly lint with pre-0.1.2 rules and reported 92 false findings). An engine
  executing from the plugin cache now refuses hook-driven work (`record`,
  `maintain`) when its version differs from the installed marketplace manifest,
  logging a "restart Claude Code" hint; nothing is lost — reconcile re-records
  skipped sessions and due jobs run on the next current-engine session start.
  `wiki doctor` gains a `version` row reporting engine/installed parity and any
  stale cache dirs. Dev checkouts and the marketplace clone never trip the
  guard.

### Changed

- **Transcript-format drift resolved for the 2026-07 entry types.** The cleaner
  now recognizes seven new Claude Code JSONL entry types: `agent-name` becomes
  a session-title fallback (`ai-title` still wins), `pr-link` surfaces in the
  cleaned body as `PR: repo#number` — deliberately never the URL, which would
  trip the ingest risk gate downstream — and `file-history-delta`,
  `agent-setting`, `worktree-state`, `relocated`, `frame-link` are recognized
  non-content metadata. The drift tally prunes types the engine has since
  learned, so doctor stops warning after an upgrade instead of alerting forever
  on stale counts.

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
