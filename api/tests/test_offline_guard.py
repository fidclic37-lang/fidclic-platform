"""
The API tests run offline (PR #454).

Twice in one PR the CI failed where a laptop passed: a test asked the internet
(an e-mail domain's DNS, a commune's name) and the CI's answer differed from
the laptop's « unreachable ». scripts/run_api_tests.py now runs every file
with tests/_offline on its path: any lookup of a host that is not this
machine is refused at once — the same « unreachable » everywhere — and the
runner names the file and the host so the test can be given a stub.

Run: cd api && python3 tests/test_offline_guard.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))


PROBE = r'''
import socket, sys, time
out = []
t = time.time()
try:
    socket.getaddrinfo("api-adresse.data.gouv.fr", 443)
    out.append("outside: resolved")
except OSError:
    out.append("outside: refused")
out.append("fast" if time.time() - t < 1 else "slow")
try:
    socket.getaddrinfo("localhost", 80)
    out.append("localhost: resolved")
except OSError:
    out.append("localhost: refused")
try:
    import httpx
    httpx.get("https://dns.google/resolve?name=x.fr", timeout=3)
    out.append("httpx: answered")
except Exception as e:
    out.append("httpx: " + type(e).__name__)
print("|".join(out))
'''


def main():
    spec = importlib.util.spec_from_file_location("run_api_tests", os.path.join(ROOT, "scripts", "run_api_tests.py"))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    print("Le runner prépare un environnement hors ligne")
    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "net.tsv")
        env = runner.offline_env(log, base={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": "/somewhere",
                                            "HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"})
        guard = os.path.join(ROOT, "api", "tests", "_offline")
        check("the guard comes first on PYTHONPATH, the rest kept",
              env["PYTHONPATH"].split(os.pathsep)[:2] == [guard, "/somewhere"], env.get("PYTHONPATH"))
        check("it knows where to write", env.get("FIDCLIC_OFFLINE_LOG") == log)

        print("\nUn test qui demande Internet")
        probe = os.path.join(tmp, "test_probe.py")
        with open(probe, "w") as f:
            f.write(PROBE)
        t = time.time()
        r = subprocess.run([sys.executable, probe], env=env, capture_output=True, text=True, timeout=60)
        said = (r.stdout.strip().splitlines() or [""])[-1].split("|")
        check(f"another host is refused ({said})", "outside: refused" in said, r.stderr[-400:])
        check("…at once, no timeout to wait for", "fast" in said and time.time() - t < 30)
        check("this machine still answers (local servers, mongod)", "localhost: resolved" in said)
        check("an HTTP client fails like a laptop without network, even with a proxy set",
              any(s.startswith("httpx: ") and s != "httpx: answered" for s in said), said)
        hits = runner.net_hits(log)
        check(f"the runner can name the file and the hosts ({hits})",
              hits == [("test_probe.py", "api-adresse.data.gouv.fr"), ("test_probe.py", "dns.google")])
        check("no log, no hits", runner.net_hits(os.path.join(tmp, "nothing.tsv")) == [])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
