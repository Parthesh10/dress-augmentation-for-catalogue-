"""Run every test file, each in its own process.

Same runner as the sibling project, and for the same reason: no pytest, no
discovery magic, and every file is runnable on its own so a test gets run
while you are working on the thing it covers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"


def main() -> int:
    files = sorted(HERE.glob("test_*.py"))
    if not files:
        print("no test files found")
        return 1
    failures, passed, t0 = [], 0, time.perf_counter()
    for f in files:
        print(f"\n--- {f.name} " + "-" * max(0, 56 - len(f.name)))
        proc = subprocess.run(
            [sys.executable, str(f)], capture_output=True, text=True,
            cwd=str(HERE.parent), env={**os.environ, "PYTHONPATH": str(SRC)},
        )
        out = (proc.stdout or "").rstrip()
        if out:
            print(out)
        if proc.returncode != 0:
            print((proc.stderr or "").rstrip())
            failures.append((f.name, proc.stderr or ""))
        else:
            passed += sum(1 for line in out.splitlines() if line.startswith("pass "))
    dt = time.perf_counter() - t0
    print("\n" + "=" * 64)
    if failures:
        print(f"{len(failures)} file(s) FAILED: {', '.join(n for n, _ in failures)}")
        return 1
    print(f"{len(files)} files, {passed} tests, all pass  ({dt:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
