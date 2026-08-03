# tests/test_path_parity.py — the prompt-free-recall contract couples three files by one literal
# engine path: commands/wiki.md invokes it, settings.json's Bash allow-rules whitelist it, and
# install.sh's ENGINE default resolves the same location. Nothing at runtime detects drift between
# them (a path rename in one silently re-introduces permission prompts on every /wiki query), so
# this test pins the parity.
import re
from sync_util import ROOT

CANON = "~/.claude/plugins/marketplaces/claude-wiki/bin/wiki"

# 1. commands/wiki.md runs the canonical path (CLAUDE_PLUGIN_ROOT is dev-fallback only).
cmd = (ROOT / "commands" / "wiki.md").read_text()
assert "`%s $ARGUMENTS`" % CANON in cmd, \
    "commands/wiki.md must invoke the canonical engine path %s" % CANON
print("ok 1: commands/wiki.md invokes the canonical engine path")

# 2. every settings.json Bash allow-rule whitelists that same path prefix.
import json
rules = json.loads((ROOT / "settings.json").read_text())["permissions"]["allow"]
bash_rules = [r for r in rules if r.startswith("Bash(")]
assert bash_rules, "settings.json must ship Bash allow-rules"
for r in bash_rules:
    assert r.startswith("Bash(%s " % CANON), \
        "allow-rule %r does not target the canonical engine path %s" % (r, CANON)
print("ok 2: all %d settings.json Bash allow-rules target the canonical path" % len(bash_rules))

# 3. install.sh's ENGINE default resolves the same location (via $CLAUDE_DIR, which defaults
#    to $HOME/.claude — the same root the "~" in the canonical path expands to).
sh = (ROOT / "install.sh").read_text()
m = re.search(r'(?m)^ENGINE="\$\{WIKI_INSTALL_ENGINE:-(.+)\}"', sh)
assert m, 'could not find ENGINE="${WIKI_INSTALL_ENGINE:-...}" in install.sh'
suffix = CANON.split("~/.claude", 1)[1]                      # /plugins/.../bin/wiki
assert m.group(1) == "$CLAUDE_DIR" + suffix, \
    "install.sh ENGINE default %r must resolve the canonical path" % m.group(1)
assert 'CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"' in sh, \
    "install.sh must resolve CLAUDE_DIR from CLAUDE_CONFIG_DIR with the $HOME/.claude default"
print("ok 3: install.sh ENGINE default resolves the canonical path")
