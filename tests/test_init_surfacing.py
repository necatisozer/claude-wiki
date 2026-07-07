# tests/test_init_surfacing.py — sync/init design surfacing: hint, status line, doctor sync block.
from sync_util import make_wiki, make_origin, wire_origin, run, enable_sync
from pathlib import Path
import shutil, tempfile

HINT = "Fresh wiki (local-only)."

w = make_wiki()                                   # git repo → no hint
r = run(["digest"], w); assert HINT not in r.stdout, r.stdout

nw = Path(tempfile.mkdtemp(prefix="wiki5_")) / "wiki"   # not a repo → hint (R14: any count)
(nw / "journal" / "2026").mkdir(parents=True)
(nw / "journal" / "2026" / "x.md").write_text("---\nsid: s\n---\nnote\n")
r = run(["digest"], nw); assert HINT in r.stdout, r.stdout + r.stderr

r = run(["status"], nw); assert "local-only" in r.stdout, r.stdout
o = make_origin(); wire_origin(w, o); enable_sync(w)
r = run(["status"], w); assert "armed (origin/main)" in r.stdout, r.stdout

r = run(["doctor"], w)
out = r.stdout
assert "sync" in out and "hook" in out, out       # armed block: sync, hook, remote lines
(w / ".githooks").mkdir(exist_ok=True)
r = run(["doctor"], nw); assert "local-only" in r.stdout, r.stdout
print("ok test_init_surfacing")
