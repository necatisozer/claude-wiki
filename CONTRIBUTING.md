# Contributing

Thanks for looking at `claude-wiki`. It is a small, deliberately constrained codebase. A few rules keep
it that way — please read them before opening a PR.

## Running the tests

The suite is **stdlib-only** — there is no `pytest`, no dependencies, nothing to install:

```
python3 tests/run.py
```

`tests/run.py` runs each `tests/test_*.py` in its own subprocess from the repo root and prints a
`N/N passed` line. CI runs exactly this on `ubuntu-latest` and `macos-latest` (see
`.github/workflows/ci.yml`). The runners have no `claude` CLI, no `gh` auth, and no git identity — the
tests shim or skip all three, so the suite must pass in a bare environment.

## Ground rules

- **Single-file engine.** The whole engine is one file, `bin/wiki`, using only the Python 3 standard
  library. Do not split it into modules and do not add third-party dependencies — the "one stdlib file"
  property is what makes it trivially auditable and installable. Same for the tests.
- **Tests ship with fixes.** Any behavior change lands with the test that covers it in the same PR. A
  bug fix without a regression test is incomplete.
- **No credential literals — ever.** No authored file (engine, tests, docs, prompts) may contain a
  string that matches the secret-gate patterns; a self-scan test fails CI forever if one does. When a
  test needs a credential-shaped value, **construct it at runtime** (concatenate/format the pieces) so
  the literal never appears in the source. In docs, use obvious placeholders (e.g. `AKIA...`, not a real
  20-character key).
- **POSIX-only.** macOS / Linux / WSL. The engine relies on `fcntl` locking, `O_NOFOLLOW`, and POSIX
  scheduling and fails fast on native Windows — don't add code paths that assume otherwise.
- **Security invariants are load-bearing.** Stage-then-promote writes, untrusted-text framing at every
  LLM boundary, deterministic (never model-emitted) gates, and the secret gate are not optional
  niceties — see [ARCHITECTURE.md](ARCHITECTURE.md). Preserve them; if a change touches one, say so
  explicitly in the PR.

## Where things live

- `bin/wiki` — the engine (command dispatch is at the bottom, in `main()`).
- `prompts/` — the system prompts for the record / ingest / lint LLM steps.
- `SCHEMA.md` — the editorial rulebook the engine inlines into ingest/lint (this repo's copy is the
  authoritative one).
- `skills/wiki/SKILL.md` — the operating manual served to Claude sessions.
- `tests/` — the stdlib test suite.
- `ARCHITECTURE.md` — pipeline, trust boundaries, config reference, divergences.
