"""
scripts/run_api_tests.py runs the files several at a time (2026-11-20: the
CI job was cut at its 30 minutes on PR #504 with every file green — 24 min on
#503, the suite keeps growing).

    · the results come back in the files' order, whatever finishes first
    · a failing file is still named, with its line; a passing one is « ok »
    · N at a time really is faster than one after the other
    · API_TEST_JOBS sets N; 1 runs them one by one, as before; nonsense → 1
    · every file still runs offline (the guard on its PYTHONPATH)

Run: cd api && python3 tests/test_api_runner.py
"""
import importlib.util
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:300]}"))


def main():
    spec = importlib.util.spec_from_file_location("run_api_tests", os.path.join(ROOT, "scripts", "run_api_tests.py"))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    tmp = tempfile.mkdtemp()
    files = {
        "test_a_slow.py": "import time; time.sleep(1.2); print('1 passed, 0 failed')",
        "test_b_fail.py": "print('  ✗ the thing broke'); raise SystemExit(1)",
        "test_c_quick.py": "print('1 passed, 0 failed')",
        "test_d_slow.py": "import time; time.sleep(1.2); print('1 passed, 0 failed')",
        "test_e_slow.py": "import time; time.sleep(1.2); print('1 passed, 0 failed')",
        "test_f_env.py": "import os, sys; sys.exit(0 if os.environ.get('PYTHONPATH','').startswith(sys.argv[1]) else 3)",
    }
    os.makedirs(os.path.join(tmp, "tests"))
    for n, body in files.items():
        with open(os.path.join(tmp, "tests", n), "w") as f:
            f.write(body + "\n")
    names = sorted(files)
    env = runner.offline_env(os.path.join(tmp, "net.tsv"))

    print("Plusieurs à la fois")
    t0 = time.time()
    res = runner.run_files(names, env, cwd=tmp, jobs=4, args={"test_f_env.py": [runner.OFFLINE]})
    fast = time.time() - t0
    check(f"in the files' order ({[n for n, _ in res]})", [n for n, _ in res] == names)
    codes = dict((n, r.returncode) for n, r in res)
    check(f"each file's own answer ({codes})",
          codes == {"test_a_slow.py": 0, "test_b_fail.py": 1, "test_c_quick.py": 0, "test_d_slow.py": 0,
                    "test_e_slow.py": 0, "test_f_env.py": 0})
    check("the failing file's line is the ✗ one", runner._why(dict(res)["test_b_fail.py"]) == "✗ the thing broke")
    check("every file still runs offline (the guard first on its PYTHONPATH)", codes["test_f_env.py"] == 0)
    t0 = time.time()
    runner.run_files(names, env, cwd=tmp, jobs=1, args={"test_f_env.py": [runner.OFFLINE]})
    slow = time.time() - t0
    check(f"4 at a time is faster than one by one ({fast:.1f}s vs {slow:.1f}s)", fast < slow * 0.7 and slow >= 3.4)

    print("\nCombien à la fois")
    os.environ.pop("API_TEST_JOBS", None)
    check(f"by default, the machine's processors ({runner.jobs()})", runner.jobs() == max(1, min(os.cpu_count() or 1, 4)))
    for raw, want in (("1", 1), ("3", 3), ("0", 1), ("-2", 1), ("abc", 1), ("64", 16)):
        os.environ["API_TEST_JOBS"] = raw
        check(f"API_TEST_JOBS={raw!r} → {want}", runner.jobs() == want, runner.jobs())
    os.environ.pop("API_TEST_JOBS", None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
