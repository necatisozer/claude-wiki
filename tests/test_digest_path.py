# tests/test_digest_path.py — run: python3 tests/test_digest_path.py
# digest runs against a throwaway seeded WIKI_HOME, never the live memory repo.
#
# WP3 digest redesign: the digest no longer DUMPS the topic/project map inline ([[slug]] — desc
# lines); the full map is read on demand from index.md. This test pins the surviving invariants:
#   * the `/wiki query` slash command is referenced (recall-on-demand),
#   * no hardcoded engine filesystem path (`bin/wiki query`),
#   * data-dir paths are templated from WIKI_HOME (no hardcoded ~/.claude/wiki),
#   * the full topic map is NOT dumped inline (map on demand via index.md).
import tempfile
from pathlib import Path
from sync_util import run   # run() points WIKI_HOME at the temp wiki

w = Path(tempfile.mkdtemp(prefix="wiki5_dig_"))
(w / "pages" / "topics").mkdir(parents=True)
(w / "journal").mkdir()
(w / "config.json").write_text('{"enabled": true}')
(w / "pages" / "topics" / "seed.md").write_text(
    "---\nname: Seed\nslug: seed\ndescription: seed topic for digest test\n---\nseed\n")
out = run(["digest", "--cwd", str(w)], w)
assert out.returncode == 0, out.stderr
d = out.stdout
# CHANGED (was `assert "[[seed]]" in d`): the redesign does NOT inline the topic/project map — it is
# read on demand from index.md — so a seeded topic must NOT be dumped as a [[link]] map entry.
assert "[[seed]]" not in d, "the full topic map must NOT be dumped inline (map on demand)"
assert "seed topic for digest test" not in d, "page descriptions must not be injected (map on demand)"
assert "index.md" in d, "digest must point at the on-demand routing index (index.md)"
assert "/wiki query" in d, "digest must reference the /wiki query slash command"
assert "bin/wiki query" not in d, "digest must NOT hardcode the engine filesystem path"
assert str(w) in d, "data-dir paths must be templated from WIKI_HOME (no hardcoded user path)"
print("PASS test_digest_path")
