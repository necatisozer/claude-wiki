#!/usr/bin/env python3
# tests/run.py — stdlib runner: each tests/test_*.py in its own subprocess, from the repo root.
#   python3 tests/run.py            # exits non-zero if any test fails
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    if not tests:
        print("no tests found under", ROOT / "tests"); return 1
    failed = []
    for t in tests:
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, str(t)], cwd=str(ROOT),
                               capture_output=True, text=True, timeout=600)
            ok, out, err = r.returncode == 0, r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:
            # TimeoutExpired yields bytes even under text=True
            dec = lambda b: b.decode(errors="replace") if isinstance(b, bytes) else (b or "")
            ok, out, err = False, dec(e.stdout), dec(e.stderr) + "\nTIMEOUT (600s)"
        print("%s %-28s (%.1fs)" % ("PASS" if ok else "FAIL", t.name, time.time() - t0), flush=True)
        if not ok:
            failed.append(t.name)
            sys.stdout.write(out); sys.stderr.write(err); sys.stderr.flush()
    print("\n%d/%d passed" % (len(tests) - len(failed), len(tests)))
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
