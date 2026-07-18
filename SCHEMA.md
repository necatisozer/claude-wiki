# Wiki SCHEMA — the editorial guide

This file is the rulebook for maintaining the wiki. Every LLM ingest/lint step reads it first.

## Layers (what lives where)
- **Raw sources** (immutable): the Claude Code `.jsonl` transcripts under `~/.claude/projects/**`. Referenced, never copied.
- **Journal** (`journal/**/*.md`): one transient per-session summary each. **Fuel, not nodes.** After a journal entry is ingested it serves as provenance only; `maintain` automatically archives ingested entries older than `journal.archive_after_days` under `journal/archive/` (never deleted). **Never index journal entries.**
- **The durable wiki = `pages/topics/` + `pages/projects/` ONLY.** These are the cross-referenced nodes.
- **`index.md`**: a catalog of topic + project pages (regenerated mechanically — do NOT hand-edit; never lists sessions).

## Core Principle
**Sessions are memory, not nodes.** The wiki you browse/query is a small, concept-centric set of topic + project pages. Per-session detail stays in the journal (transient) and is folded *into* these pages — never added as its own node.

## Page types & frontmatter

### Topic page — `pages/topics/<slug>.md`
A distinct concept, entity, technique, tool, or decision-area you would link to from elsewhere.
```yaml
---
name: <Human Title>
description: <one-line, ≤120 chars>
type: topic
slug: <kebab-case>
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active            # active | stale | contradicted
---
```
Body: synthesized prose (your words, not journal quotes) + `[[other-topic]]` cross-refs. End with a `## Sources` list.

### Project page — `pages/projects/<slug>.md`
A codebase / product you work on (e.g. `beybisi-kmp`, `klibs`, `home`).
```yaml
---
name: <project>
description: <one-line, ≤120 chars>
type: project
slug: <project-slug>
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active            # active | stale | contradicted
---
```
Body sections (omit empty ones): `## What this is` · `## Conventions & decisions` · `## Active threads` (open follow-ups) · `## Dropped / avoided approaches` (dead ends — so a future session doesn't re-litigate them) · `## Related topics` ([[links]]) · `## Sources`.

## Journal entry — `journal/YYYY/MM/<date>__<slug>__<sid8>.md`
One transient per-session summary, written by `record` (never hand-authored). **Fuel, not a node** — ingest folds it into pages and never indexes it. The frontmatter is a fixed machine contract (emitted by `write_journal`); do not rely on any other keys:
```yaml
---
name: "<session title>"        # JSON-quoted
description: "<one-line, ≤120 chars>"   # JSON-quoted; the classifier repairs over-length, rejects wordless
type: session                  # always "session" — the create/index passes skip this type
sessionId: <full session id>   # the Claude Code session UUID; the ## Sources citation shows its first 8 (sid8)
project: <project-label>       # derived from the session cwd (or "-")
gitBranch: <branch or empty>
date: <YYYY-MM-DD>             # the session end date; also the journal path's date segment
started: <ISO-8601 or empty>
ended: <ISO-8601>
model: <models seen, comma-joined>
tools: <Tool×N, …  or "none">
files_touched: <int>
subagents: <int>
ingested: false                # flips to true at ingest-commit time — the DURABLE, git-synced fold marker
source: <path to the raw .jsonl transcript>   # provenance; the transcript itself is never copied
---
# <session title>

<synthesized session summary body>
```
- **`ingested`** is the source of truth for "already folded": `reindex` rebuilds ledger state from it, so history is never re-folded through the LLM. `ingest --accept` and re-records preserve it in place (keeping the filename stable so `## Sources` citations don't dangle).
- **`sessionId`** is the join key. Page `## Sources` bullets cite the first 8 chars (`sid8`); to verify a claim, open the journal entry whose `sessionId` starts with that `sid8`.
- Bodies are secret-redacted at write time (a raw credential never lands here). Old ingested entries are archived (never deleted) under `journal/archive/YYYY/MM` after `journal.archive_after_days`.

## Rules for ingest/lint
1. **Merge, don't accumulate.** Fold new facts into the *existing* relevant page. Create a new page only for a genuinely distinct concept (the create-vs-update heuristic: *new page = a distinct entity/concept you'd link to from elsewhere; edit in place = an attribute/update of an existing page*).
2. **Synthesize, never echo.** State the gist in your own words. Don't paste journal/report/code verbatim.
3. **Anchor every claim to a source.** Each topic/project page ends with `## Sources` listing the journal entries it draws from: `- YYYY-MM-DD · <sid8> · <one-line>`. A claim with no traceable source doesn't belong — and conversely, keep `## Sources` to the citations that back *current* claims (drop a citation when its fact is superseded or removed, but never strand a live claim).
4. **Cross-reference.** Link related concepts with `[[slug]]`. Update backlinks on pages you touch (under-updating cross-refs is the #1 drift failure).
5. **Conflicts — classify severity.** *Soft* (a newer source supersedes/evolves an older claim): newest wins, but **never silently delete** the old — add a bullet `⚠️ CONTRADICTION (YYYY-MM-DD): <old> vs <new>` citing both sources, set `status: contradicted`, and continue. *Hard* (a direct, mutually-exclusive conflict about the CURRENT state that needs human adjudication): still write the ⚠️ note, but also surface it as `hard_contradiction:` in the ingest SUMMARY — the run is **held for review, not auto-committed**. When unsure, treat it as soft.
6. **Dangling `[[links]]` are informational** — a write-this-later stub, not an error.
7. **Never reproduce credentials/secrets.** Abstract them.
8. **Density & proactive split:** terse, factual — a page should be scannable in under a minute. Keep **project** pages to conventions / decisions / active-threads; when a subsystem, feature, or tool accretes its own detail, extract it into a linked `[[topic]]` page instead of growing the project page. Prefer a new topic over a long section — split *before* a page bloats, not after lint flags it.
9. **Capture dead ends.** When a session abandoned an approach or explicitly chose X over Y, record it under the project page's `## Dropped / avoided approaches` — a future session shouldn't re-litigate a known dead end. (Distinct from removed *dependencies*/features, which belong in conventions/decisions.)
