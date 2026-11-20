#!/usr/bin/env python3
"""Run every api/tests/test_*.py and say which ones failed.

Each file is a standalone script that exits non-zero when a check fails, so
there is no test runner to lean on — this is it. The same command runs in CI
and on a laptop:

    python3 scripts/run_api_tests.py            # everything
    python3 scripts/run_api_tests.py security   # only files whose name matches
    API_TEST_JOBS=1 python3 scripts/run_api_tests.py   # one after the other

The files run several at a time — the machine's processors, 4 at most, or
API_TEST_JOBS (2026-11-20: the CI job was cut at its 30 minutes on PR #504
with every file green; 24 min on #503). Each file is its own process on its
own in-memory database, so they do not share anything; the results are still
printed in the files' order.

Every file runs OFFLINE (api/tests/_offline, PR #454): a lookup of any host but
this machine is refused at once, so the CI — which has the internet — reads
the same as a laptop that may not. A file that tried is named at the end with
the host; give that test a stub (it still runs, with « unreachable »).

KNOWN_RED is the list of tests already failing on main the day this started.
They are tolerated so the check can go in without a week of unrelated repair,
and the list is the debt: a test on it that starts passing fails the run too,
so nobody can leave it there once it is fixed.
"""
from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(HERE, "api", "tests")
OFFLINE = os.path.join(TESTS, "_offline")

# Failing on main since before this check existed. Remove a name when its test
# is fixed — the run tells you to.
# empty since 2026-10-28 (#387): the three first ones are fixed — keep it so
KNOWN_RED: set = set()


def offline_env(log: str, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment a test file runs in: the offline guard first on the
    path (its sitecustomize refuses any host but this machine) and where it
    writes the hosts it refused."""
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = os.pathsep.join([OFFLINE] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    env["FIDCLIC_OFFLINE_LOG"] = log
    return env


def net_hits(log: str) -> List[Tuple[str, str]]:
    """(file, host) each test tried to reach, once each, sorted."""
    try:
        with open(log) as f:
            rows = {tuple(line.rstrip("\n").split("\t", 1)) for line in f if "\t" in line}
    except OSError:
        return []
    return sorted(rows)


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


MAX_JOBS = 16


def jobs() -> int:
    """How many files run at a time: API_TEST_JOBS, else the processors (4 at
    most). Anything that is not a number from 1 up → 1, one after the other."""
    raw = os.environ.get("API_TEST_JOBS")
    if raw is None:
        return max(1, min(os.cpu_count() or 1, 4))
    try:
        n = int(raw)
    except ValueError:
        return 1
    return min(n, MAX_JOBS) if n >= 1 else 1


def run_files(names: List[str], env: Dict[str, str], cwd: str, jobs: int = 1,
              args: Optional[Dict[str, List[str]]] = None) -> List[Tuple[str, subprocess.CompletedProcess]]:
    """Run each tests/<name> in `cwd`, `jobs` at a time; the answers in the
    order of `names`, whatever finishes first."""
    def one(name: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, os.path.join("tests", name), *((args or {}).get(name, []))],
                              cwd=cwd, env=env, capture_output=True, text=True)
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return list(zip(names, pool.map(one, names)))


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    names = sorted(f for f in os.listdir(TESTS)
                   if f.startswith("test_") and f.endswith(".py") and pattern in f)
    if not names:
        print(f"no test file matches {pattern!r}")
        return 1

    broke, fixed = [], []
    log = os.path.join(tempfile.mkdtemp(prefix="fidclic-offline-"), "net.tsv")
    env = offline_env(log)
    t0 = time.time()
    n = jobs()
    print(f"{len(names)} files, {n} at a time")
    for name, r in run_files(names, env, cwd=os.path.join(HERE, "api"), jobs=n):
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
    hits = net_hits(log)
    if hits:
        print("\nThese tried the internet (refused — the run is offline). Give each a stub:")
        for name, host in hits:
            print(f"    {name} → {host}")
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
