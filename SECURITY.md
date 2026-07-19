# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do not open a public issue for a security
problem. Use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**), or email the maintainer at the address on their GitHub
profile. Include a description, affected version/commit, and a minimal reproduction if you have one.
You'll get an acknowledgement and a fix or mitigation timeline; please allow a reasonable disclosure
window before publishing details.

## Security posture (in brief)

`claude-wiki` treats **all** transcript, journal, page, and pulled text as untrusted data at every LLM
boundary, and it never lets a model-emitted field be a security gate — gates are computed
deterministically in the engine (including citation resolution: a fold citing a `sid8` with no
matching journal entry, or creating a page whose identity near-collides with an existing one, is held
for review — model output can add a hold, never clear one). Writes are stage-then-promote (atomic, no
symlink follow; symlink and gitlink blobs are rejected on write and on pull). A secret gate redacts credential shapes before any
LLM sees the text and before anything is written, and a per-commit scan fail-closes a push that would
leak a secret to the remote. Recalled memory is injected only as a defanged, inert digest sandbox, and
all engine LLM calls run with tools disabled, so a poisoned transcript cannot make the engine act. A
transport allowlist and `GIT_ALLOW_PROTOCOL` pin constrain git remotes, and a `schema_version` guard
refuses to run against data written by a newer engine. The engine is POSIX-only. Full detail:
[ARCHITECTURE.md](ARCHITECTURE.md).

## Install integrity

The `curl … | bash` one-liner **cannot verify its own checksum** — a script piped straight into a shell
has no independent copy to check against. Security-conscious users should **download the installer
first, inspect it, and run it locally**:

```
curl -fsSLO https://raw.githubusercontent.com/necatisozer/claude-wiki/v0.1.0/install.sh
# read install.sh, then:
bash install.sh
```

Running it locally also gives the installer a real terminal, so it can prompt for confirmation instead
of assuming `--yes`.
