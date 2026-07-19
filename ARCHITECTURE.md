# Architecture

`claude-wiki` turns Claude Code session transcripts into a private, git-backed markdown memory and
feeds the relevant parts back into future sessions. This document describes what **ships** — the
pipeline, the code/data boundary, the trust model, the recall model, the data layout, the config
reference, and the deliberate divergences from the original design.

The engine is a single Python 3 file (`bin/wiki`, stdlib only, POSIX only). It is distributed as a
Claude Code plugin. Two hooks drive it: **SessionEnd** records; **SessionStart** injects the digest and
kicks the (detached) scheduled maintenance.

## Two roots: `CODE_ROOT` ↔ `DATA_DIR`

This split is the publish boundary — public code, private memory.

| | `CODE_ROOT` | `DATA_DIR` (a.k.a. `WIKI_HOME`) |
|---|---|---|
| What | the shipped plugin (this public repo) | your private memory repo |
| Where | `~/.claude/plugins/marketplaces/claude-wiki/` | `~/.claude/wiki` (override with `$WIKI_HOME`) |
| Holds | engine, `prompts/`, `SCHEMA.md`, `hooks/`, `commands/`, `settings.json` | `pages/ journal/ state/ config.json index.md logs/` |
| Visibility | public | **private** (your own GitHub repo) |

The engine resolves `CODE_ROOT` from `__file__` and `DATA_DIR` from `$WIKI_HOME`, so the code can live
in the plugin cache while every read/write still hits the real memory. The **editorial rulebook** the
engine inlines into ingest/lint prompts is the plugin's `CODE_ROOT/SCHEMA.md` — a `SCHEMA.md` inside a
memory repo, if present, is author residue and is never read.

## The pipeline (record → journal → ingest → pages → digest)

A one-way flow; each stage is bounded and gated.

```
  SessionEnd hook
      │
      ▼
  clean_transcript ──▶ record ──▶ classify_record ──▶ journal/ ──▶ ingest ──▶ pages/ ──▶ index.md
   deterministic       haiku →     deterministic       per-      two-phase    topic +      auto-
   parse; redacts      a journal   gate:               session   sonnet:      project      generated
   secrets before      entry       junk→skipped;       entries   ① select     pages        catalog
   any LLM sees it                 leak/injection/                ② fold
                                   secret→fail-closed
      ▲                                                                                        │
      │                                                                                        ▼
  SessionStart hook ◀───────────────── digest injection ◀──────────────────────── (recents + orientation)
```

1. **`clean_transcript`** — deterministic parse of the raw `.jsonl` transcript into a compact header +
   body; drops non-content entry types; **redacts secret shapes before any LLM sees the text**.
2. **`record`** (haiku) — summarizes the cleaned session into a one-entry journal draft.
3. **`classify_record`** — a **deterministic** gate computed from the engine, not a model field:
   greeting/no-substance → **skipped** (content-free ledger marker, no journal); chain-of-thought /
   system-prompt / tool-transcript leakage, prompt-injection shapes, or secret/PII shapes →
   **fail-closed reject** (content-free marker naming only the failure *class*). Only a clean record is
   journaled. Bodies are secret-redacted again at write time.
4. **`journal/`** — one transient per-session entry (fuel, not a node). Frontmatter contract in
   [`SCHEMA.md`](SCHEMA.md).
5. **`ingest`** (sonnet, **two-phase, index-first**): **① select** — the model sees the compact
   `index.md` (one line per page) + the new journal entries and returns the relevant existing pages
   (capped at `ingest.max_selected_pages`); **② fold** — only those selected page bodies (+ `SCHEMA.md`
   + the journal entries) are loaded into a single-shot prompt that emits `FILE:` blocks. This removes
   the context ceiling and keeps the "model physically can't rewrite the whole wiki" safety property.
6. **`pages/`** — the durable wiki (topic + project pages), the browsable/queryable nodes.
7. **`digest`** — injected at the next SessionStart (see Recall).

Scheduling is **cron-based** and **hook-triggered**: `maintain` (detached, run from SessionStart) does
crash-gap **reconcile**, due-based ingest (daily) and lint (weekly), and journal retention, all under
one lock. A job is "due" when its cron has fired since it last ran, so a missed occurrence is caught up
on the next session rather than needing a precise timer.

## Recall model

Recall is **pull-based** and has **no MCP server and no embedding/semantic search** — three plain
surfaces:

1. **The digest** (auto-injected, passive): a bounded orientation — a static, `WIKI_HOME`-templated
   intro, the latest `digest.recent_sessions` recents (∪ every un-ingested session, hard-capped by
   `digest.max_recent_lines`), and the project names the memory covers. The **full topic/project map is
   not injected** — it is read on demand from `index.md`. Descriptions are inert-quoted (URLs,
   tool-call shapes, and imperatives defanged) — the digest is a *sandbox*, never a channel for
   instructions.
2. **`wiki query "<terms>"`** — **FTS5 keyword search** over pages + journal, run via **Bash**
   (the search is the one thing that needs code). `--include-archive` reaches archived entries.
3. **Claude's built-in `Read`** — open any page under the memory repo directly. Read is read-only, so
   it prompts on no path by default; the digest points, query finds, Read opens.

Since 0.1.10 the record step also **captures each session's recall usage** (Phase A of index
convergence): `wiki query` calls — hit/miss classified from the paired tool result — and Reads of
wiki files land as an engine-computed `recall:` key in the journal entry's frontmatter, terms
ASCII-folded and whitelist-sanitized. Counts surface in `wiki status`; the terms themselves are
never displayed or injected (they are attacker-seedable via a poisoned transcript, so they wait
inert until a future, deliberately-designed Phase B folds recurring demand into `index.md` — not
built yet: measured organic volume is ~1 recall session/month, below any honest threshold).

Awareness lives in the digest; depth lives in the on-demand primitives. The plugin ships scoped
allow-rules (`Bash(...wiki query|status|doctor:*)` + `Read(~/.claude/wiki/**)`) so these read surfaces
run prompt-free — see the README's permission-setup note (plugin-shipped permissions are not yet
auto-granted by Claude Code, so users copy the rules into their own settings).

## Trust boundaries / security model

The design principles: **treat all transcript/journal/page/pulled text as untrusted data at every LLM
boundary**; **never let a model-emitted field be a security gate — compute gates deterministically in
the engine**; **stage-then-promote every write**. Concretely:

- **Stage-then-promote writes.** Every write goes through a symlink-free staging dir with
  `O_NOFOLLOW|O_CREAT|O_EXCL` then an atomic `os.replace`; symlink / mode-120000 (gitlink) blobs are
  rejected on write **and** on pull. One pattern closes the symlink-follow RCE, atomic-write drift, and
  the held-page-on-disk leak.
- **Untrusted-text sentinels at every LLM boundary.** `call_claude` is the single LLM choke: it fences
  the user turn in a per-call **random sentinel** and appends a boundary directive, and it neutralizes
  the engine's own `===` / `-----` structural delimiters at the start of any untrusted line, so a body
  can't forge a fake SCHEMA rule, "existing page", or `FILE:` block. All engine LLM calls also run
  `--tools "" --disable-slash-commands --strict-mcp-config --no-session-persistence`, so a poisoned
  transcript **cannot make the engine act** — the blast radius is bounded to the content it writes.
- **Passive-memory digest sandbox.** Recalled text is inert-quoted: URLs → `[link removed]`, tool-call
  shapes stripped, code fences demoted, leading imperatives tagged `[inert]`. The digest reads
  **committed HEAD only**, so an uncommitted/held page never reaches a live session.
- **Deterministic risk-gated auto-accept.** `ingest.mode: auto` (default) folds under an
  engine-computed hold: a batch that overwrites a tracked page, exceeds the diff cap, or carries a
  risky shape (imperative / 2nd-person / URL / secret / PII) is HELD (staged, uncommitted) for review.
  `ingest.mode: review` always stages. A model-emitted `hard_contradiction:` line is honored only
  **fail-closed**: a non-`none` value adds a hold, but the field can never clear one — the engine
  never trusts model output to *allow* a commit, so an injection that blanks the field changes nothing.
- **Secret gate.** A redactor masks credential/secret shapes (AWS keys, GitHub/Slack tokens, private
  keys, JWTs, connection strings, Stripe/Google keys, high-entropy assignments, …) **before** the LLM
  sees the transcript **and** at write time; a **per-commit** scan (including commit messages)
  fail-closes a push that would leak a secret to the remote. The engine never persists matched secret
  text unmasked anywhere it writes (logs, ledger, reports).
- **Transport allowlist.** `wiki init <target>` accepts only an `owner/repo` slug, an `https://`/`ssh`
  URL, or a local path; it rejects leading-`-` option-injection and `::` transport-helper forms.
  Process-wide `GIT_ALLOW_PROTOCOL=https:ssh:file` belts every git/gh child.
- **Sync-boundary parity.** Pulled pages/journal pass the same symlink/secret/size/UTF-8 gates as
  local writes; the engine does not trust an inbound `ingested:` flag from the remote.
  Instruction-shaped text is deliberately **not** a pull reject (a lone URL in a legitimately synced
  page must not wedge all future sync) — it is neutralized at read time by the digest sandbox instead.
- **Schema-version migration guard.** `config.json` carries a durable `schema_version`. On a mutating
  command the engine compares it to its own `ENGINE_SCHEMA`: older → run the idempotent migration
  chain; **newer → refuse** (an older engine must never corrupt data a newer one wrote).
- **POSIX-only.** The engine fails fast on native Windows (it relies on `fcntl` locking, `O_NOFOLLOW`,
  and POSIX scheduling). WSL is the supported Windows route. Doctor also probes FTS5 availability.

## Data layout (under `DATA_DIR`)

- `pages/topics/`, `pages/projects/` — the durable wiki nodes.
- `journal/` — transient per-session entries; ingested entries archived (never deleted) under
  `journal/archive/YYYY/MM` after `journal.archive_after_days`.
- `index.md` — auto-generated page catalog (never hand-edited; never lists sessions).
- `lint-report.md` — latest lint sweep.
- `config.json` — settings (synced). `state/config.local.json` — per-device overrides (untracked;
  holds the `sync` block). `SCHEMA.md` — data-repo copy is author residue, not read.
- `state/` — local, rebuildable: the ledger (sqlite), locks, run-stamps, `push_blocked`, `drift.json`;
  gitignored. `logs/wiki.log` — engine log (size-capped, one rotation).

## Configuration reference

Defaults live in `DEFAULT_CONFIG` (seeded into `config.json` at init). Doctor validates this same set —
unknown keys, wrong types, and out-of-range values are **advisory** (listed, non-gating); a
`config.local.json` that fails to *parse* is **critical**. Models use floating family aliases
(`haiku`/`sonnet`) so they track the `claude` CLI's current pin.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whole-wiki kill switch. |
| `schema_version` | `2` | Durable data-format version; the forward-compat guard reads it. |
| `record.model` | `haiku` | Model for the per-session record step. |
| `record.input_max_chars` | `60000` | Cap on cleaned-transcript chars fed to record. |
| `record.subagent_cap` | `30` | Max subagent transcripts folded into one record. |
| `record.max_assistant_chars` | `1200` | Per-assistant-turn char cap in the cleaned body. |
| `record.max_user_chars` | `1500` | Per-user-turn char cap in the cleaned body. |
| `digest.recent_sessions` | `12` | How many recents the digest lists. |
| `digest.max_chars` | `4000` | Hard cap on the injected digest size. |
| `digest.max_recent_lines` | `20` | Hard cap on recent lines (backlog can't explode the digest). |
| `digest.project_scope` | `false` | Limit recents to the active project (cross-project-bleed guard). |
| `reconcile.enabled` | `true` | Auto crash-gap catch-up in `maintain`. |
| `reconcile.window_days` | `14` | How far back reconcile scans (0 = no cap). |
| `backfill.pace_seconds` | `0.5` | Delay between records during an opt-in history seed. |
| `ingest.model` | `sonnet` | Model for the fold step. |
| `ingest.mode` | `auto` | `auto` = deterministic risk gate · `review` = always stage for human accept. |
| `ingest.cron` | `0 20 * * *` | Auto-ingest schedule (local time, 5-field cron). |
| `ingest.enabled` | `true` | Enable scheduled auto-ingest (cron kept when false). |
| `ingest.max_sessions_per_run` | `50` | Cap on sessions folded per scheduled run. |
| `ingest.auto_max_batches` | `4` | Cap on auto-committed batches per run. |
| `ingest.max_selected_pages` | `12` | Phase-① cap on selected existing pages. |
| `ingest.stall_threshold` | `20` | Un-ingested backlog past this → stall banner. |
| `lint.model` | `sonnet` | Model for the weekly full-wiki lint sweep. |
| `lint.cron` | `0 20 * * 1` | Lint schedule (local time). |
| `lint.enabled` | `true` | Enable scheduled lint. |
| `lint.max_page_lines` | `160` | Page-length lint cap. |
| `lint.desc_max_chars` | `120` | Description-length lint cap. |
| `lint.stale_projects_days` | `60` | Report-only staleness window for **project** pages: an `active` page whose newest freshness evidence (`created:`/`updated:`/newest Sources date) is older flags in lint. `0` = off. Distinct from `doctor.stale_after_days` (days since last *record*). |
| `lint.stale_topics_days` | `0` | Same for **topic** pages — off by default (durable external facts don't decay on a timer). |
| `doctor.stale_after_days` | `7` | Days since last record → "possibly stale" note (0 = off). |
| `doctor.probe_timeout_seconds` | `20` | Per-probe timeout so a hung tool can't wedge doctor. |
| `journal.archive_after_days` | `90` | Archive ingested journal entries older than this (0 = off). |
| `limits.max_file_bytes` | `2000000` | Max file size the engine will read/write. |
| `limits.max_line_chars` | `1000000` | Max single-line length. |
| `limits.max_transcript_chars` | `2000000` | Max raw transcript size processed. |

Two config surfaces are **not** in `DEFAULT_CONFIG`:

- **`projects.exclude`** — an optional list of path prefixes in `config.json`; a session whose cwd is
  under one is skipped at record time (never captured).
- **`sync`** — lives only in the per-device, untracked `state/config.local.json` (written by `init`):
  `sync.enabled` (armed?), `sync.branch` (default `main`), `sync.auto_push` (default `true`).

## Divergences from the original design

These are deliberate departures the release consciously made:

- **Dropped MCP recall, semantic search, Ollama, and embeddings.** An earlier design shipped an MCP
  server (3 tools) and an Ollama embedding layer. Both were removed: recall is now **digest injection +
  `wiki query` (FTS5) + built-in Read**. MCP tools are ask-by-default (they gate like Bash), whereas
  built-in Read is zero-prompt — the "MCP bypasses read friction" premise was backwards. Semantic
  search was only ever measured against brute-force cosine, never against LLM index-first routing, so
  it was dropped (re-gate only if the keyword baseline ever proves insufficient).
- **Budgets and the `ollama:<model>` backend descoped.** No `*_max_usd` budget knobs; cost is governed
  instead by `ingest.max_sessions_per_run`, `ingest.auto_max_batches`, and the `record.*` input caps.
- **Sessions subsume notes.** No `query --save` / `wiki note` — recorded sessions are the memory
  substrate, so a separate note-compounding surface was unnecessary (and generated answers must never
  re-enter as sources). Since 0.1.8 the record step preserves durable *analytical* outcomes — review
  verdicts, comparison results, facts learned, decisions not to act — as `## Findings` bullets even
  when no file changed; only sessions that leave nothing a future session could use still collapse to
  a one-line summary. (Before 0.1.8, every no-durable-outcome session collapsed — a documented trade
  that measurably lost review verdicts.)
- **The schema is fixed, not co-designed.** The original design invites each user to co-evolve their
  own schema document with their agent. A distributed plugin needs a stable editorial contract — the
  engine's gates and tests assume it — so one `SCHEMA.md` ships in `CODE_ROOT` for every install and
  a copy inside a memory repo is ignored. Users customize operational config (crons, caps,
  `ingest.mode`, exclusions), never the taxonomy or editorial rules.
- **The map is not injected.** The digest carries bounded recents + orientation only; the full
  topic/project link graph is read on demand from `index.md` (Karpathy's routing-file model) rather
  than pushed into every session.
- **Passive digest + auto-accept vs. a pure-pull model.** The one deliberate philosophical departure
  from a strict "no auto-injected context, 100% pull" memory model: claude-wiki keeps a **passive-memory
  digest** and **deterministic risk-gated auto-accept** so memory works with zero user effort. The
  escape hatch for users who want full control is **`ingest.mode: review`** (stage every fold for human
  acceptance); the digest sandbox and the deterministic gate bound the risk of the auto path.
- **Other conscious "no"s:** no `wiki config` command (an editor + `doctor` suffice); no `wiki
  uninstall` command (documented manual path instead); no native Windows and no CJK tokenization / full
  i18n; the `trusting` blanket-auto ingest mode was not shipped; the plugin keeps the name `wiki`.
