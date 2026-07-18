# claude-wiki

> ⚠️ **Pre-stable (0.1.x).** The first public release has shipped; semver 0.x signals the API and
> on-disk formats may still change before **1.0.0**. Install from the latest release tag (below), not
> from `main`.

A Claude Code plugin that gives Claude **persistent, cross-session memory**. A SessionEnd hook records
what happened in each session into a private, git-backed markdown wiki; a SessionStart digest plus
on-demand keyword search (`wiki query`) and Claude's built-in file reads bring the relevant parts
back. The memory lives in **your own private GitHub repo** and stays in sync across every machine you
run it on.

## Install (clean machine)

```
gh auth login
curl -fsSL https://raw.githubusercontent.com/necatisozer/claude-wiki/v0.1.5/install.sh | bash
```

This installs the plugin, verifies the install actually took, and runs `wiki init` to set up your
memory — restoring it from your existing repo if you have one, or creating a fresh one otherwise.

By default `wiki init` derives your memory repo from your GitHub identity: **`<your-gh-login>/claude-wiki-memory`**
(a private repo it creates/attaches via `gh`). It fails closed if `gh` is missing or unauthenticated —
it never falls back to anyone else's namespace. To restore from or create a specific repo instead, pass
it after `--`:

```
curl -fsSL https://raw.githubusercontent.com/necatisozer/claude-wiki/v0.1.5/install.sh | bash -s -- owner/repo
```

The piped one-liner always passes `--yes`, because a script arriving over a pipe has no terminal
attached for interactive confirmation prompts. Security-conscious users can inspect the script and run
it with a real stdin instead of piping it (the piped form cannot self-verify its own checksum):

```
curl -fsSLO https://raw.githubusercontent.com/necatisozer/claude-wiki/v0.1.5/install.sh
bash install.sh
```

## Requirements

POSIX only — **macOS, Linux, or Windows via WSL** (native Windows fails fast with a clear message; the
engine relies on `fcntl` locking, `O_NOFOLLOW`, and POSIX paths). You need:

- **`python3`** (3.8+, standard library only — nothing to `pip install`; the engine and tests are stdlib)
- **`claude`** — the Claude Code CLI (the engine calls `claude -p` for the record/ingest/lint steps)
- **`git`** — the memory is a git repo
- **`gh`** — the GitHub CLI, authenticated (`gh auth login`), used to derive your identity and
  create/attach the private memory repo. Only required for the default (no-arg) init path.

## Privacy

Your memory is **yours and private**. Nothing leaves your machine except commits to **your own private
GitHub repo**. The plugin separates two roots:

- **`CODE_ROOT`** — the shipped plugin (this public repo): engine, prompts, schema, manifests.
- **`DATA_DIR`** — your private memory at `~/.claude/wiki` (or `$WIKI_HOME`): pages, journal, config.

That boundary is the publish line: code is public, memory is private. Additional protections:

- A **secret gate** redacts credential/secret shapes before any text reaches an LLM *and* before it is
  written to disk, and a per-commit scan fail-closes a push that would leak a secret to the remote.
- **`projects.exclude`** (a list of path prefixes in `config.json`) skips recording any session whose
  working directory is under an excluded path — for client repos or anything you never want captured.
- All record/ingest/lint LLM calls run with tools disabled (`--tools "" --disable-slash-commands
  --strict-mcp-config --no-session-persistence`), so a poisoned transcript cannot make the engine *act*.

## Cost

The engine calls the Claude API on your account. Rough governors:

- **record** runs on **haiku**, once per finished session.
- **ingest** runs on **sonnet**, folding only the ~10 **selected** page bodies (a two-phase, index-first
  design — not the whole corpus) plus the new journal entries; daily by default.
- **lint** runs on **sonnet**, weekly.

Ballpark **~$2–5/month** of API usage at moderate activity, **scaling with your volume and page count**
(ingest re-sends selected page bodies, so cost grows as the wiki grows). Tune with
`ingest.max_sessions_per_run`, `ingest.auto_max_batches`, `ingest.cron`, and the `record.*` input caps
(see the config reference in [ARCHITECTURE.md](ARCHITECTURE.md)).

## How it works

Each session flows through a one-way pipeline; recall is a separate, pull-based path.

```
  SessionEnd hook
      │
      ▼
  clean_transcript ──▶ record ──▶ classify_record ──▶ journal/  ──▶ ingest ──▶ pages/
  (deterministic,      (haiku →   (deterministic     (per-session  (two-phase   (topic +
   redacts secrets)     entry)     gate: junk→skip,   entries)      sonnet:      project
                                   leak/inject/secret               ① select     pages)
                                   →fail-closed)                    ② fold)
                                                                        │
  SessionStart hook ◀── digest injection ◀───────── index.md ◀─────────┘

  Recall  =  digest (bounded recents + orientation, map on demand)
           +  wiki query   (FTS5 keyword search, run via Bash)
           +  Read         (open any page, prompt-free)
```

Writes are **stage-then-promote** (atomic, no symlink follow), auto-accept is **risk-gated and
deterministic** (never a model-emitted field), and every LLM boundary treats transcript/page text as
**untrusted data** fenced in a per-call sentinel. There is **no MCP server and no embedding/semantic
layer** — search is keyword-only. Full detail: [ARCHITECTURE.md](ARCHITECTURE.md).

## Permission setup (recommended — copy 4 rules)

For the recall surfaces to run **prompt-free**, Claude needs read-only auto-allow for the wiki's read
commands. The plugin ships these four scoped rules in [`settings.json`](settings.json), but **Claude
Code does not yet auto-grant permissions from a plugin** — a plugin-shipped `permissions` block is
currently inert. Until the platform honors it, copy the four rules into your **own**
`~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(~/.claude/plugins/marketplaces/claude-wiki/bin/wiki query:*)",
      "Bash(~/.claude/plugins/marketplaces/claude-wiki/bin/wiki status:*)",
      "Bash(~/.claude/plugins/marketplaces/claude-wiki/bin/wiki doctor:*)",
      "Read(~/.claude/wiki/**)"
    ]
  }
}
```

These are **read-only**: keyword search, status, health check, and reading your own memory. Everything
that mutates (ingest/sync/init) still prompts. Skip this and the wiki still works — you'll just get a
permission prompt the first time each read command runs.

## Uninstall

There is no `wiki uninstall` command (by design). To remove: `claude plugin uninstall
wiki@claude-wiki`, unset the repo's `core.hooksPath` if you set it, and — only if you want to —
`rm -rf ~/.claude/wiki` and delete the private GitHub repo. Full steps are in
[`skills/wiki/SKILL.md`](skills/wiki/SKILL.md).

## Everything else

Day-to-day commands, sync internals, scheduling, and troubleshooting live in
[`skills/wiki/SKILL.md`](skills/wiki/SKILL.md) — the plugin's operating manual. The architecture,
trust boundaries, config reference, and deliberate divergences from the original design are in
[ARCHITECTURE.md](ARCHITECTURE.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Security policy:
[SECURITY.md](SECURITY.md).
