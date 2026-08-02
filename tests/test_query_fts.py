# tests/test_query_fts.py — run: python3 tests/test_query_fts.py
# WP3 recall: `wiki query` is FTS5 keyword search over pages + journal — no embeddings, no LLM,
# no network. Throwaway WIKI_HOME (make_wiki) seeded with 3 docs; assert a keyword query returns
# the right page, a distinct keyword hits a different doc, and a non-matching query returns nothing.
import json
from sync_util import make_wiki, run

w = make_wiki()   # seeds pages/topics/seed.md ("seed page")
(w / "pages" / "topics" / "dependency-injection.md").write_text(
    "---\nname: Dependency Injection\n---\nHilt and Koin wire dependencies at the graph root.\n")
(w / "journal" / "2026" / "07" / "sess.md").write_text(
    "---\nname: Session notes\nsessionId: s1\n"
    'recall: [{"q":"velvet armadillo","hit":false}]\n'
    "---\nDebugged a flaky pagination cursor today.\n")

# keyword hit → the DI page (not the seed page, not the journal entry)
r = run(["query", "dependencies", "--json"], w)
assert r.returncode == 0, r.stderr
paths = [h["path"] for h in json.loads(r.stdout)]
assert any(p.endswith("dependency-injection.md") for p in paths), paths
assert not any(p.endswith("seed.md") for p in paths), paths

# a distinct keyword routes to a different doc (the journal entry)
paths2 = [h["path"] for h in json.loads(run(["query", "pagination", "--json"], w).stdout)]
assert any(p.endswith("sess.md") for p in paths2), paths2
assert not any(p.endswith("dependency-injection.md") for p in paths2), paths2

# hyphenated term (FTS5 bareword syntax error) → tokenized-AND retry, not exact-phrase-only:
# "graph-root wire" appears nowhere verbatim, but every word is on the DI page
paths3 = [h["path"] for h in json.loads(run(["query", "graph-root wire", "--json"], w).stdout)]
assert any(p.endswith("dependency-injection.md") for p in paths3), paths3

# a recorded recall term must NOT be searchable — else a re-run of a missed query "hits" the
# entry that recorded the miss (self-referential match)
assert json.loads(run(["query", "velvet armadillo", "--json"], w).stdout) == []

# non-matching query → empty JSON …
assert json.loads(run(["query", "zzzznonexistentterm", "--json"], w).stdout) == []

# … and a clean human-readable "no matches" on the plain path
assert "no matches" in run(["query", "zzzznonexistentterm"], w).stdout

print("PASS test_query_fts")
