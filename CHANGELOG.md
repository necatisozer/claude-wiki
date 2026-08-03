# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **The v0.1.13 derived-conflict auto-heal was dead code in production.**
  `log.md` rides in every record/ingest/retention commit and the synced
  transcript copy rides in every record commit, so the heal's authored-file
  fail-closed check aborted on every real multi-device conflict — the device
  stayed diverged and every push failed, exactly the wedge the heal was built
  to remove. Journal entries, transcript copies (byte-exact — they are gzip),
  and the op-log lines this device added since the merge base are now
  re-applied on top of the remote — with per-file one-sidedness verified, not
  assumed: a both-devices edit of the same file (e.g. a remote re-redaction), a
  local log-line removal, or any authored file still fails closed; a committed
  local DELETION is re-applied, never resurrected from the remote. The heal
  refuses to run over uncommitted work (a held batch, an in-progress
  hand-edit), makes every fail-closed decision before the destructive reset,
  and unwinds to the pinned `sync-preconflict` branch on any post-reset
  failure, so a half-healed tree (local commits stripped, unvalidated remote
  content live) can no longer survive it.
- **A fold block aimed at an existing page outside the phase-1 selection no
  longer loses its facts silently.** The overwrite was correctly refused, but
  the batch still committed and marked its sessions `ingested`, dropping the
  refused block's content forever. The batch is now HELD (on the manual path
  too, even when nothing else was written), the block is stashed in
  `state/ingest-refused.md` for hand-merge — secret-shaped spans masked, later
  batches appending rather than clobbering an un-merged stash — and the ingest
  prompt now tells the fold model the page list is partial and to never
  re-emit a page it wasn't given.
- **Held-batch quarantine bypasses closed.** (1) `index.md` is no longer
  regenerated from the unreviewed working tree while a batch is staged/held —
  live sessions Read `index.md` directly, so staged page descriptions leaked
  around the committed-HEAD quarantine; `--accept` rebuilds it after review.
  (2) The pending/held flags are written BEFORE risk-gated pages hit disk, so
  a crash mid-stage can no longer leave held content live. (3) The LLM lint
  report is defanged (`_inert_report`: URLs + tool-call shapes) before landing
  in `lint-report.md` — previously the one LLM output path written unsanitized.
- **`install.sh` now honors a real TTY.** SECURITY.md/README promised that
  downloading and running the installer locally allows interactive confirms,
  but `--yes` was unconditional; it is now passed only when stdin is not a
  terminal. Unattended automation that allocates a pty (`ssh -t`, CI wrappers)
  sets `WIKI_INSTALL_YES=1` to force `--yes`.
- **Docs pointed at a dead installer.** SKILL.md's "New machine?" line and
  SECURITY.md's inspect-then-run example pinned `v0.1.0/install.sh`, whose
  exact-version gate hard-fails against the current marketplace; both now track
  the current release, and CONTRIBUTING.md documents the release-time sweep of
  every pinned URL.

## [0.1.17] - 2026-08-03

The hardening release: a high-effort adversarially-verified review of the whole
engine confirmed ten defects — durable-state ordering bugs that silently strand
or lose recorded knowledge, gaps where unreviewed content could reach a live
session, and two packaging breaks — all fixed here, followed by a four-angle
cleanup sweep that collapsed the duplication the fixes exposed.

### Fixed

- **A resumed session that now skips/rejects no longer clobbers its ledger
  row.** `_record_skip` used INSERT OR REPLACE, so a transcript that grew into
  a classifier skip nulled the prior good row's `page_path`/`ingested_at` —
  orphaning a journal entry that was still on disk and cited. It now UPDATEs
  in place (like the error path always did): provenance survives, only
  status/skip_reason/mtime advance.
- **A failed ingest commit reverts the durable `ingested:` flags.** Both the
  auto batch and `ingest --accept` flipped journal frontmatter to
  `ingested: true` *before* committing; on commit failure the flips stayed on
  disk, the next `reindex` seeded `ingested_at` from them, and the promised
  retry never ran — the batch's knowledge never reached committed pages. Flags
  now roll back whenever the commit fails.
- **`wiki query` honors the held-ingest quarantine.** While a batch was HELD,
  the FTS index read staged (possibly attacker-poisoned) pages from the
  working tree — bypassing the committed-HEAD-only rule the digest already
  enforced. Both readers now share one quarantine (`_quarantined_page_read`):
  held → committed HEAD, new-and-uncommitted → skipped.
- **Risky-shaped journal snippets are withheld from query output.** Journal
  bodies never pass a review gate (pages do), so `--include-journal` could
  serve an injection-shaped payload into a live session before ingest's hold
  ever fired. A hit whose entry carries risky shapes keeps its path + title
  but the snippet is replaced with a content-free class list.
- **Lint's secret net re-includes the `high_entropy` backstop.** It was
  narrowed in 0.1.2 to dodge false positives that 0.1.11's
  `_looks_like_code_identifier` later fixed structurally — but lint was never
  re-widened, leaving the weekly sweep (the only retroactive scan over content
  already on the remote) blind to unknown-provider credentials.
- **Lint's injection net covers the ingest gate's combo shapes.** Override
  clauses, attack verbs (curl/wget/exfiltrate) and the imperative+URL exfil
  combo now tag as `injection` over already-landed content, so a poisoned page
  that entered outside the record/ingest path (restored repo, hand edit) is
  surfaced. imperative+2nd-person stays write-gate-only — ordinary prose
  addressed to the reader trips it.
- **The derived-conflict auto-heal is loud and checked.** Its re-apply commit
  now injects the fallback git identity and verifies the return code (a silent
  failure used to report "auto-resolved" while journal entries sat
  uncommitted), and any local pages/ content replaced by the remote is named
  in the committed oplog with a pointer to the `sync-preconflict` recovery
  branch — a hand-edit can no longer vanish with only a debug log line.
- **`install.sh` honors `CLAUDE_CONFIG_DIR`.** The manifest and engine paths
  were hardcoded to `$HOME/.claude`, so a relocated config dir hard-failed the
  installer at the version gate.
- **Prompt-free recall works again.** `/wiki` invoked the engine via
  `${CLAUDE_PLUGIN_ROOT}` (the version-keyed plugin cache), which the shipped
  allow-rules never matched — every query prompted. The command now runs the
  marketplace path the rules grant (cache path kept as dev fallback), and a
  new parity test pins the path contract across `commands/wiki.md`,
  `settings.json`, and `install.sh` so drift breaks CI instead of recall.

### Changed

- **Duplication collapsed into single homes** (4-angle cleanup sweep): the
  held-page quarantine, the `ingested:` frontmatter rewrite, secret detection
  (`_iter_secret_matches` everywhere, including the retro-scrub), the
  `claude -p` argv/envelope contract (doctor now probes the exact production
  invocation), the commit primitive, gh url/create resolution, non-blocking
  job locks, state stamps, tool-result text extraction, and the un-ingested
  rows query. Also: lint scans secrets once per document instead of twice,
  the ingest hold gate spawns one git subprocess per block instead of three,
  cron specs parse once per walk instead of per probed minute, and ~115
  phantom-nested lines plus dead code (`git_commit`, `_head_page_text`,
  unused params) are gone. No behavior changes intended.

## [0.1.16] - 2026-08-03

The gist-alignment release: a live divergence hunt against the running system
(not the code alone) found four gaps between the engine and its own design
intent — all closed here, plus the tooling that fell out of closing them.

### Added

- **Cross-device transcript durability (`record.sync_transcripts`, default off).**
  Claude Code deletes raw session transcripts on its `cleanupPeriodDays` timer,
  after which a page claim could only be verified against the journal entry —
  an LLM-written summary, not raw data. Each kept session's transcript is now
  written as a secret-REDACTED gzip at `transcripts/<sid>.jsonl.gz`, a tracked
  file committed and pushed with the record: same trust class as the journal
  (nothing lands unredacted; redaction runs line-by-line before compression,
  since the pre-push scanner cannot see inside a .gz). Files ≥95 MB are
  skipped; failures never fail a record. A raw local tier
  (`record.archive_transcripts`, gzip into untracked `state/transcripts/`) is
  also available for byte-faithful local retention.
- **`wiki transcript <sid8> [--raw]`** — the last hop of the
  page → journal → transcript verification chain in one read-only command:
  prints the cleaned, redacted rendering (header + readable body) of the
  session an sid8 cites, `--raw` for the stored JSONL. Falls back to Claude
  Code's raw store inside its cleanup window, redacting on output. Ships with
  a fifth scoped allow-rule.
- **Durable operations log (`log.md`).** One engine-written, unix-parseable
  line per record / ingest / lint / retention pass, append-only, committed
  with the operation that wrote it — the gist's `log.md`, previously split
  across the ledger (machine-only sqlite) and a rotating debug log.
- **Doctor: `sources` and `scrub` checks.** `sources` counts journal `source:`
  transcripts already deleted by `cleanupPeriodDays` (the erosion was
  invisible; on the author's machine 339/399 were already gone). `scrub`
  re-scans the synced transcript tier with the *current* secret patterns —
  masks are idempotent, so any hit is content the upload-day patterns missed —
  cached per (file sha256, engine version); findings name sid8 + pattern class
  only, never matched text.
- **Lint suggests questions (report-only).** The weekly report now ends with a
  `## Suggested questions` section: at most 5 questions for the human — long-
  untouched active threads, follow-ups recurring without an outcome,
  unresolved contradicted pages. No severity tags, never counted as findings,
  never proposed edits: "lint detects, humans decide" stands.
- **Obsidian as the reading surface (docs + gitignore).** `pages/` is already
  a valid Obsidian vault; README documents the zero-config path, and the
  required gitignore now covers `.obsidian/` and `.trash/` at any depth so
  vault state never enters the synced repo. Deliberately no `wiki obsidian`
  command.

### Changed

- **`wiki query` is pages-only by default.** BM25 length normalization let
  short raw journal entries outrank the long synthesized pages they were
  folded into — measured live: a broad query ranked five session notes above
  the first page. The wiki's answers are its pages; `--include-journal` opts
  session notes back in for drill-downs, and `--include-archive` implies it.
- **`CLAUDE_CONFIG_DIR` honored.** The transcript store, default data dir, and
  plugin marketplace/cache paths all derive from one `CLAUDE_DIR` (Claude
  Code's relocation knob, stock `~/.claude` fallback); the SessionEnd shim
  follows the same rule. `WIKI_HOME` still wins for the data dir.

### Fixed

- **Recall capture no longer poisons itself.** Captured miss-query terms were
  stored in journal frontmatter *and* FTS-indexed, so re-running a missed
  query "hit" the very entry that recorded the miss; capture also swallowed
  shell plumbing (`2>&1 | head -1` became "2 1 head") and `--limit`'s value.
  The `recall:` line is now stripped from the FTS body, and term extraction
  truncates at the first unquoted shell operator and skips flag values.
- **A hyphenated search term no longer silently degrades the whole query.**
  `ad-hoc` or `music-ai` is an FTS5 bareword syntax error, and the old
  fallback matched only the query as an exact phrase. On syntax error the
  query now retries with each word individually quoted (literal terms,
  implicit AND) before the phrase fallback.

## [0.1.15] - 2026-08-02

### Fixed

- **A session's project is now identified by its git remote, not its working
  directory.** `project_label()` returned the cwd basename, so the label was
  whatever directory the session happened to sit in. Every git worktree became a
  project of its own — a repo's per-ticket worktrees each produced a throwaway
  single-session "project" — as did directories with no repository at all
  (`~/Downloads`, a bare projects parent). The serious case is attribution:
  because a rename moves the checkout but not the repo, one project's sessions
  could be folded into a *different* project's page, and such a batch can
  survive repeated clean lint sweeps, since lint detects inconsistency and a
  uniformly-wrong label is perfectly consistent.

  `origin`'s repo name is stable across all of it — git resolves it identically
  from a worktree, a submodule, or any subdirectory. The lookup is read-only
  (`remote get-url` reads `.git/config`, never the network), 5s-capped,
  fail-quiet and cached per process, so the SessionStart digest path is
  unaffected.

  The basename remains the fallback for anything with no repo or no origin
  (`~/Downloads`, a fresh un-pushed checkout) — which is how every pre-existing
  label was derived, so **repos whose directory already matches their remote
  keep the label they have and no existing history is re-labeled**. `HOME` keeps
  its unconditional special case, so a dotfiles checkout at `~` cannot rename it.

  Malformed or unparseable remotes fall back to the basename rather than being
  sanitized: a bad parse must never mint a malformed project name into journal
  frontmatter, the ledger and the FTS index.

## [0.1.14] - 2026-08-02

### Fixed

- **A manual `wiki lint` now stamps `state/last_lint`.** Only the `--if-due`
  cron path wrote the timestamp, so running `wiki lint` by hand refreshed
  `lint-report.md` and `state/lint_open` but left `last_lint` at whatever the
  last scheduled sweep set. Two consequences: `wiki status` kept reporting a
  stale "last lint" date long after a fresh sweep, and the weekly cron still
  considered lint due, re-running a full-corpus LLM sweep that had just
  completed. The manual path now stamps *after* `run_lint` returns a report —
  the cron path deliberately stamps first, to close a duplicate-run window that
  a manual invocation does not have, so only a completed sweep counts.

## [0.1.13] - 2026-07-20

### Added

- **Multi-device derived-file conflict auto-heal.** Two devices folding on the
  same schedule both rewrite `pages/` and `index.md`, so the second to pull hit
  a rebase conflict — and the old path (abort, flag, proceed) left that device
  silently diverged until a human resolved it by hand. The data model already
  settles this: the journal is the source of truth and pages are *derived* from
  it (ingest folds journal → pages; `reindex_ledger` re-seeds ingested state
  from each entry's `ingested:` frontmatter), and journal files are
  one-per-session so they can never conflict. When every local change since the
  merge base is a journal entry or a derived artifact, the conflict now resolves
  mechanically: the remote's derived files are taken wholesale, this device's
  journal entries are re-applied on top marked **un-ingested**, and the next
  ingest re-folds them. Nothing is lost — every page is reconstructible from
  journal entries both devices already hold.
- **Fails closed.** A single local change outside `journal/` and the derived set
  (config, prompts, docs — anything authored) aborts the auto-heal and falls
  back to flag-and-proceed. Discarding a hand-edited file to win a merge is
  never the right trade. The pre-reset HEAD is pinned to a `sync-preconflict`
  branch first, so no local commit becomes unreachable even if the re-apply
  dies midway. The post-pull validation gate still runs on the healed HEAD.
- Ledger `ingested_at` is cleared explicitly for re-applied entries —
  `reindex_ledger` COALESCEs that column, so the frontmatter flip alone would
  not have forced the re-fold.

### Note

`ingest.cron` lives in the synced `config.json`, so every device inherits the
same fold schedule and collides by construction. Stagger it per device via the
local-only `state/config.local.json` (deep-merges over `config.json`):
`{"ingest": {"cron": "30 21 * * *"}}`.

## [0.1.12] - 2026-07-20

### Fixed

- **`doctor` no longer flags a key the engine itself requires.** `activated_at`
  is stamped into `config.json` by `_stamp_activated_at` and read by
  `_reconcile_since` as reconcile's lower scan bound, but it has no
  `DEFAULT_CONFIG` entry — and `_config_schema` derives its known-key set from
  `DEFAULT_CONFIG` plus the runtime *sections*. So a perfectly healthy wiki
  reported `config.json: unknown key 'activated_at'` on every `doctor` run.
  Advisory-only, but it put permanent noise in a health check that should read
  clean, and invited a "fix" by deleting the stamp — which would silently widen
  reconcile's scan back to the `window_days` cap. Top-level runtime scalars now
  have their own known-key map (`CONFIG_RUNTIME_SCALARS`). The entry is a typed
  known key, not a blanket skip: a non-string `activated_at` is still flagged.

## [0.1.11] - 2026-07-20

### Fixed

- **Code identifiers no longer read as credentials.** The `high_entropy`
  catch-all flags any ≥32-char run mixing lower + UPPER + digit — a shape that
  describes a random API key *and* every long camelCase/snake_case identifier.
  On a real KMP corpus `linkPodDebugFrameworkIosSimulatorArm64` (38) and the
  Kotlin/Native mangled symbol
  `kniprot_cocoapods_AmplitudeSwift0_NSPredicateValidating` (55) both matched,
  and because the gate is fail-closed, two false positives refused an entire
  `init` restore. The exclusions already in place (git SHA, UUID, single-case
  base64) all work by *missing a character class*; identifiers miss none, so
  they needed a structural test. A candidate is now exempt when it decomposes
  into word-like tokens: ≥65% of characters in alphabetic tokens of ≥4 chars
  **and** ≤10% digits. Measured over 200k synthetic keys per length, 0.107% of
  32–64 char credentials satisfy both, against 14/14 real identifiers exempted.
  The relaxation is confined to the unknown-provider backstop — every named
  provider pattern (AWS, GitHub, Stripe, Google, Slack, JWT, `assignment`,
  `conn_string`) remains absolute, and the per-commit push gate is unchanged.

### Changed

- `scan_secrets` and `_redact_secrets` now share one `_iter_secret_matches`
  chokepoint, so detection and redaction cannot disagree about what counts as a
  secret — the write-path parity the init gate depends on.

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
