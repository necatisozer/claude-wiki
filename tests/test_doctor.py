# tests/test_doctor.py — run: python3 tests/test_doctor.py
# doctor is read-only reporting; run it against a throwaway WIKI_HOME so the labels
# (incl. data-repo) hold on machines with no live memory repo and no claude (CI).
import subprocess, sys, tempfile
from pathlib import Path
from sync_util import ENGINE
import os
w = Path(tempfile.mkdtemp(prefix="wiki5_doc_"))
(w / "config.json").write_text('{"enabled": true}')
out = subprocess.run([sys.executable, ENGINE, "doctor"], capture_output=True, text=True,
                     env={**os.environ, "WIKI_HOME": str(w)})
assert out.returncode == 0, out.stderr
for label in ("python3", "claude", "git", "gh", "data-repo"):
    assert label in out.stdout, "doctor must report %s" % label
assert str(w) in out.stdout, "data-repo line must show the WIKI_HOME in use"
print("PASS test_doctor")
