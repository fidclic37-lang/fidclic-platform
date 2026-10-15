#!/usr/bin/env python3
"""Run every api/tests/test_*.py and say which ones failed.

Each file is a standalone script that exits non-zero when a check fails, so
there is no test runner to lean on — this is it. The same command runs in CI
and on a laptop:

    python3 scripts/run_api_tests.py            # everything
    python3 scripts/run_api_tests.py security   # only files whose name matches

KNOWN_RED is the list of tests already failing on main the day this started.
They are tolerated so the check can go in without a week of unrelated repair,
and the list is the debt: a test on it that starts passing fails the run too,
so nobody can leave it there once it is fixed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(HERE, "api", "tests")

# Failing on main since before this check existed. Remove a name when its test
# is fixed — the run tells you to.
KNOWN_RED = {
    "test_dashboard_home.py",       # one check of the home figures
    "test_einvoicing_lifecycle.py", # 401 « Webhook verification unavailable »
    "test_fec.py",                  # « export is audited »
}


def _why(r: subprocess.CompletedProcess) -> str:
    """The line worth reading: the failed check, or the exception, or the last
    thing said. These scripts print « ✗ <check> » and a tail of counts, so the
    useful line is rarely the last one."""
    lines = [l.rstrip() for l in (r.stdout + "\n" + r.stderr).splitlines() if l.strip()]
    for l in lines:
        if "✗" in l:
            return l.strip()
    for l in reversed(lines):
        if "Error" in l or "error:" in l or "Exception" in l:
            return l.strip()
    return lines[-1].strip() if lines else "no output"


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    names = sorted(f for f in os.listdir(TESTS)
                   if f.startswith("test_") and f.endswith(".py") and pattern in f)
    if not names:
        print(f"no test file matches {pattern!r}")
        return 1

    broke, fixed = [], []
    t0 = time.time()
    for name in names:
        r = subprocess.run([sys.executable, os.path.join("tests", name)],
                           cwd=os.path.join(HERE, "api"),
                           capture_output=True, text=True)
        ok = r.returncode == 0
        known = name in KNOWN_RED
        mark = "ok  " if ok else "FAIL"
        if ok and known:
            mark, _ = "FIXED", fixed.append(name)
        elif not ok and known:
            mark = "red "          # expected, already on the list
        elif not ok:
            broke.append((name, _why(r)))
        print(f"  {mark}  {name}")

    print(f"\n{len(names)} files in {time.time() - t0:.0f}s")
    for name, why in broke:
        print(f"\n✗ {name}\n    {why[:300]}")
    if fixed:
        print("\nThese pass now — take them out of KNOWN_RED in this script:")
        for name in fixed:
            print(f"    {name}")
    if broke:
        print(f"\n{len(broke)} test file(s) broke. Run one on its own to see why:")
        print(f"    cd api && python3 tests/{broke[0][0]}")
    return 1 if (broke or fixed) else 0


if __name__ == "__main__":
    sys.exit(main())
