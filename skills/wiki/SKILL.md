---
name: wiki
description: Operating manual for the session-wiki — cross-session memory for Claude Code (the `wiki` engine / `/wiki` commands). Consult when running any wiki command (query, status, ingest, lint, doctor, sync, init), when the SessionStart digest or `wiki status` shows a lint finding / ingest HOLD / push-blocked banner, or when the user asks how the wiki records, recalls, syncs, or is uninstalled.
---

# Session-wiki — operating manual

The wiki gives Claude Code **persistent, cross-session memory**. A SessionEnd hook records each
finished session into a private, git-backed markdown wiki; a SessionStart digest plus on-demand
keyword search bring the relevant parts back. This file is the operating manual that ships **with the
plugin** — it reads correctly on any user's machine.

## Recall model (how memory comes back)
There is **no MCP server and no semantic/embedding search** — recall is three plain surfaces:
1. **The SessionStart digest** (auto-injected): a small, bounded orientation — a static intro, the
   latest recents (∪ any un-ingested sessions), and the project names the memory covers. The full
   topic/project **map is not injected**; it is read on demand from `index.md`.
2. **`wiki query "<terms>"`** — **FTS5 keyword search** over pages + journal, run via **Bash**. The
   plugin ships a scoped `Bash(...bin/wiki query:*)` allow-rule so this runs **prompt-free**. The
   digest surfaces it as `/wiki query "<terms>"`.
3. **Claude's built-in Read** — open any page under the memory repo directly (also prompt-free via the
   shipped `Read(~/.claude/wiki/**)` grant). Awareness lives in the digest; depth lives in query + Read.

## Code vs data (two roots)
- **Code** = the plugin (engine `bin/wiki`, `prompts/`, `SCHEMA.md`, the `hooks/` + `commands/`
  manifests). Installed at `~/.claude/plugins/marketplaces/necatisozer-wiki/`. The engine calls this
  `CODE_ROOT`. The editorial rulebook the engine inlines into ingest/lint is the **plugin's**
  `SCHEMA.md` (`CODE_ROOT/SCHEMA.md`) — the copy inside a memory repo, if any, is never read.
- **Data** = your memory, at `~/.claude/wiki` (override with `$WIKI_HOME`). The engine calls this
  `DATA_DIR`. It holds `pages/ journal/ state/ config.json index.md logs/` and is a private git repo.
  Every read/write hits the data repo; code can live in the plugin cache without moving your memory.

## Data layout (under the memory repo)
- `pages/topics/`, `pages/projects/` — the **durable wiki** (browsable, queryable nodes).
- `journal/` — transient per-session summaries (**fuel**; folded into pages by ingest, never nodes).
  Old ingested entries are archived (never deleted) under `journal/archive/YYYY/MM`.
- `index.md` — auto-generated catalog of pages · `lint-report.md` — latest sweep findings.
- `config.json` — settings (models, crons, caps); per-device overrides in untracked
  `state/config.local.json` (holds the `sync` block). `SCHEMA.md` (data-repo copy) — author residue, not read.
- `state/` — local, rebuildable (ledger, locks, run-stamps, `push_blocked`/`drift.json`); gitignored ·
  `logs/wiki.log` — engine log.

**Automatic:** a SessionEnd hook records each finished session into `journal/`; a SessionStart hook
injects the digest and fires the detached `maintain` compile (ingest daily / lint weekly, when due).
Everything under **Commands** is the *manual* surface — you rarely need it.

## Commands
Run in a session via the **`/wiki:wiki <cmd>`** command, or call the engine directly:
`python3 ~/.claude/plugins/marketplaces/necatisozer-wiki/bin/wiki <cmd>`. Written `wiki <cmd>` below.

**Setup / sync (per machine)**
- `wiki init [owner/repo | git-url] [--yes]` — one command, any machine state → this device synced.
  Routes by what it finds: **publish** (existing wiki, no remote: full scan, typed `PUSH` confirm →
  create/attach the private repo → first gated push → arm) · **restore** (empty machine, remote has
  memory: clone → reindex → arm; nothing is pushed) · **fresh start** (nothing anywhere: create the
  private repo, seed a skeleton, publish) · **repair** (already armed: revalidate + reinstall the
  pre-push hook if missing). Bare `wiki init` offers the default repo `<your-gh-login>/claude-wiki-memory`.
  Fail-closed everywhere; arming is always the last step.
- `wiki sync [--status | --init]` — plain `wiki sync` = pull `--rebase` → reindex → gated push.
  `--status` shows enabled/branch, HEAD vs server, ahead/behind, blocked/pull state, hook.
  `--init` is an alias for `wiki init`.
- `wiki doctor [--claude-contract]` — dependency + data-repo health check (git, gh, python, FTS5
  availability, schema version, config validation, stale-capture note). `--claude-contract` also
  probes the live `claude -p` envelope.

**Recall / status (daily)**
- `wiki query <terms> [--limit N] [--include-archive] [--json]` — FTS5 keyword search across pages +
  journal. `--include-archive` also searches archived journal entries.
- `wiki status` — enabled state, schedules (flags an `⚠ INVALID CRON`), journal count, lint state,
  sync state, recent sessions.

**Maintenance (fold + health)**
- `wiki ingest [--limit N]` — manually fold un-ingested journals → pages. In `ingest.mode: review` (or
  when the risk gate holds a batch) it **stages for review**; then `wiki ingest --accept` (commit) or
  `--reject` (discard).
- `wiki lint` — run the full-wiki sweep now → `lint-report.md`.
- `wiki reindex` — rebuild ledger rows from the journal (recovery after a lost/rebuilt `state/`).
- `wiki index` — regenerate `index.md` (rarely needed; ingest does it).

Internal / scheduled (you won't normally type these): `record`, `digest`, `maintain`,
`backfill`, `ingest --if-due`, `lint --if-due`.

**New machine?** `gh auth login`, then
`curl -fsSL https://raw.githubusercontent.com/necatisozer/claude-wiki/main/install.sh | bash`
— or run `wiki init [owner/repo]` yourself after installing the plugin. The piped installer passes
`--yes` (no TTY under curl|bash); download-then-run it for interactive confirms, or
`… | bash -s -- owner/repo` to name the memory repo explicitly.

## Principles
- The wiki is the user's memory: **the user curates; the LLM only does bookkeeping.**
- **Lint detects; humans decide fixes.** No autonomous page mutation beyond ingest.
- Every claim traces to a source. **Verify a flagged claim against its source journal entry (by its
  `sessionId`), never against a neighbouring wiki page, before changing anything** — the lint sees only
  pages, so it can misjudge a source-faithful claim.

## Scheduling (cron)
Auto-ingest and the weekly lint sweep run on standard 5-field **cron** expressions on the `ingest` /
`lint` config blocks, evaluated in the **machine's local time**:
```json
"ingest": { "cron": "0 20 * * *", "enabled": true, "mode": "auto", "max_sessions_per_run": 50, "auto_max_batches": 4 },
"lint":   { "cron": "0 20 * * 1", "enabled": true, "max_page_lines": 160 }
```
- The trigger is **hook-based** (fires on the first session *after* the cron time), not a precise
  timer: a job is due when its cron has fired since it last ran, so a missed occurrence is caught up on
  the next session. `wiki maintain` runs both jobs' due-checks under one lock.
- **Disable one job** with `"enabled": false` (its cron is kept); the top-level `"enabled": false` is
  the whole-wiki kill switch.
- **`ingest.mode`**: `auto` (default) folds under a deterministic risk gate — a batch that overwrites a
  tracked page, exceeds the diff cap, or carries a risky shape (imperative/2nd-person/URL/secret/PII)
  is HELD (staged, uncommitted) for review. `review` always stages every batch for a human `--accept`.

## Fixing lint findings — Claude-session-assisted, human-directed
When `lint-report.md` has findings (surfaced in the digest + `wiki status`), the Claude session:
1. **Presents each finding explicitly** — (a) the finding, (b) the related file(s) and lines, (c) a
   concrete fix recommendation.
2. **Waits for the user's instruction.** It never batch-fixes or decides on the user's behalf.
3. **Fixes only what the user directs** — verifying each flagged claim against its source journal (by
   `sessionId`) first, then committing per fix.

Never build or enable an autonomous `wiki lint --fix` path without explicit approval.

## Resolving a held ingest (hard contradiction)
When auto-ingest hits a **hard** contradiction (or the risk gate trips) it HOLDS: stages the batch
uncommitted, sets a flag, blocks further auto-ingest, and surfaces a banner in the digest + `wiki status`.
1. **Inspect** the staged pages: `git -C ~/.claude/wiki diff` (the model wrote both claims with a
   `⚠️ CONTRADICTION` note); `cat ~/.claude/wiki/state/ingest_held` shows the conflict if present.
2. **Resolve:** edit the flagged page to settle it (usually newest-wins — your call), remove the `⚠️`
   line, set `status: active`.
3. **Clear:** `wiki ingest --accept` (commits + resumes auto-ingest) or `--reject` (discards; the
   sessions re-queue and may re-hold, so `--accept` after editing is the real resolution).

## Push blocked / pull failed (recovery)
Sync pushes flow through a fail-closed **secret gate** (per-commit scan, incl. commit messages;
binary files under `journal/`/`pages/` refuse). If a push is blocked, the digest + `wiki status` show
the masked finding; **the local commit is safe, the remote is NOT updated.** Copy-paste recovery:
```bash
cd ~/.claude/wiki
cat state/push_blocked            # the masked finding + which commit
# redact the offending file, then rewrite the unpushed commit:
git commit -a --amend --no-edit   # (or a short interactive rebase if it isn't the tip commit)
wiki sync                         # re-runs the gate; push_blocked clears on the next clean push
```
A **pull failure** (usually a dirty tree) is surfaced the same way; local work continues — fix the
tree, then `wiki sync`. If `sync --status` shows the pre-push **hook MISSING** (e.g. after a Python
upgrade), re-run `wiki init` (or `wiki _install-hook`).

## Uninstall (document-only — there is no `wiki uninstall`)
Uninstalling is three explicit manual steps, by design (no teardown command that could get it wrong):
1. `claude plugin uninstall wiki@necatisozer-wiki` — removes the engine, hooks, and command.
2. Remove the per-device pre-push hook if you set the repo's `core.hooksPath`:
   `git -C ~/.claude/wiki config --unset core.hooksPath` (skip if unset).
3. **Optional and explicit:** delete the memory itself — `rm -rf ~/.claude/wiki` (local) and delete
   the private GitHub repo. Your memory is a normal private repo; nothing else deletes it for you.
Also drop the four wiki allow-rules from your `~/.claude/settings.json` if you copied them in.
