# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.10] - 2026-07-20

### Added

- **Recall capture (Phase A of index convergence).** Nothing recorded what a
  session had to *hunt* for, so `index.md` and the digest orientation could
  never learn from recall misses. The record step now captures each session's
  memory lookups deterministically from the transcript's actual tool calls —
  `wiki … query` Bash invocations (hit/miss classified from the paired tool
  result: `no matches for` or `--json`'s `[]` = confirmed miss; errored or
  unpaired = unknown) and Reads/Greps of wiki files — into one engine-computed
  `recall:` key in the journal entry's frontmatter. Never a model field. Terms
  are ASCII-folded (Turkish sözleşme → sozlesme, not mangled), whitelist-
  sanitized to `[a-z0-9 -]` with hyphen runs collapsed — structurally unable to
  carry a secret, URL, instruction shape, or frontmatter delimiter — capped at
  8 events/session; the digest's own literal `<terms>` suggestion is ignored.
  `wiki status` gains a **count-only** line (queries / confirmed misses / wiki
  reads): the captured terms are attacker-seedable via a poisoned transcript
  and are never displayed, injected, or interpolated anywhere.
- **Phase B is deliberately not built.** Folding recurring demand into
  `index.md` descriptions waits for real data: measured organic volume is ~1
  recall session/month, below any honest recurrence threshold — a Phase B
  shipped today would first surface engine-dev vocabulary. The signal now
  accumulates inert until there is something true to converge on.

## [0.1.9] - 2026-07-20

### Added

- **Report-only page staleness.** The full-thread audit's best-attested production
  report was "confident-but-stale memory is the dominant failure past ~day 60" —
  and the engine never looked at page age. Lint now flags an `active` page whose
  newest evidence of freshness (frontmatter `created:`/`updated:` or the newest
  dated `## Sources` bullet) is older than a per-kind window:
  `lint.stale_projects_days` (default 60) and `lint.stale_topics_days` (default
  0 = off — topic pages hold durable external facts that don't decay on a
  timer). Strictly report-only by decision: the engine never flips a status,
  writes a key, or touches the page — `status:` stays fully human/model-owned
  (the red-team found `status: stale` already carries user semantics on a real
  corpus). Clear a flag by re-verifying and bumping `updated:`, letting a fold
  touch the page, or setting a non-`active` status. Future-dated frontmatter
  beyond one day of clock skew is ignored, so a poisoned fold cannot immortalize
  a page with `updated: 2099-01-01`; `-sources` companions are exempt (old by
  construction); a malformed page skips silently rather than wedging the sweep.
  Findings feed the `lint_open` banner. Live-corpus check before release: zero
  flags (project ages 1–23 days), open count unchanged.

## [0.1.8] - 2026-07-19

Gap-fill release: the ship-ready designs from the full-thread audit of Karpathy's
LLM-wiki gist (983 comments swept, ideas verified against the code, each design
adversarially red-teamed before implementation). Two new deterministic fail-closed
gates, two write-time fixes that replace a rejected self-healing-lint framework,
record-stage exploration preservation, and two pre-existing hardenings the
red-team pass surfaced.

### Security

- **Citations now resolve or hold.** SCHEMA rule 3 ("a claim with no traceable
  source doesn't belong") is enforced, not just promised: a fold that NEWLY
  introduces a `- YYYY-MM-DD · <sid8> · …` citation matching no journal filename
  is held for review (delta-gated against HEAD, so a pre-existing dangle is a
  lint finding — never a permanent hold-loop). Resolution is computed from
  journal filenames only (live + archive; the device-local ledger is excluded on
  purpose) — model output can never make a sid8 resolve, only introduce one,
  which holds. Lint gains `bad_cite`: unresolvable sid8s on landed pages plus
  malformed Sources bullets (homoglyph separators, non-8-hex tokens — citation-
  looking lines the strict resolver would otherwise silently skip). The manual
  ingest review printout shows the same check as an advisory.
- **New-page homonym guard.** Page identity is the filename stem, so two
  concepts that slugify near-identically (`metro-di`/`metrodi`, cross-kind
  `foo`) would silently become one page. A fold creating a NEW page whose
  identity collides with an existing page (or another new page in the same
  batch) is held; folding into an existing page — the normal case — is exempt
  by construction, so the guard cannot false-positive on legitimate same-topic
  folds. An internal guard error converts to a hold (fail-closed, never a crash
  loop). Lint gains a `homonym` net over existing page identities.
- **Frontmatter delimiter is line-anchored.** `parse_frontmatter` split on the
  substring `---` anywhere, so a value containing a dash run truncated the
  machine-read block and silently dropped every key after it (`ingested:`,
  `sessionId:`, `source:` — the join keys). Found by the red-team pass and
  confirmed live: one production journal entry was parsing 13 keys short.
- **Auto-ingest commits exact paths.** The unattended batch commit passed the
  bare `pages`/`journal` pathspecs, sweeping a user's concurrent hand-edits to
  unrelated pages into an engine-authored commit. It now commits exactly the
  written pages + flipped journal entries + `index.md`. (The interactive
  `--accept` keeps the broad spec on purpose — there the user just reviewed the
  whole diff, hand-fixes included.)

### Changed

- **Record preserves analytical outcomes.** The record prompt collapses a
  session to a one-line summary ONLY when it left nothing a future session
  could use; sessions with durable analytical conclusions — review verdicts,
  comparison/measurement results, facts learned, decisions not to act — get a
  `## Findings` section even with zero file changes. Measured on the live
  corpus: ~15 of 27 one-line collapses were recoverable losses, including 12
  security-review verdicts recorded as nothing. A new prompt rule requires
  naming attack classes abstractly (like credentials), so review Findings can't
  trip the injection gates. This narrows ARCHITECTURE.md's documented
  "exploratory sessions collapse" trade.
- **Fold-write description cap.** `_finalize_ingest_pages` deterministically
  truncates an over-cap frontmatter description at write time (the same
  transform record applies), so `desc_long` lint findings stop recurring.
- **Companion re-split merges, never clobbers.** A page splitting again into an
  existing `<slug>-sources` companion now APPENDS its newly-moved citations
  (deduped, chronological); the previous overwrite deleted every
  previously-archived citation — observed live during the July backlog fold.
- **Lint corpus-size early warning.** The semantic review ships the whole
  corpus in one LLM call; from 80% of `lint.single_call_token_budget` (default
  100k tokens) the report + log warn so batched lint gets designed before the
  sweep starts failing. (Corpus today: ~33k tokens.)

Verified against the live corpus before release: the two new lint classes
produce zero findings on real data (open count unchanged), and every existing
citation resolves — the gates start clean.

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
