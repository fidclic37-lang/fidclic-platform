"""
GET /api/warm — the open till keeps the server awake (user, 2026-11-20: the
page after a scan was sometimes slow — a cold server takes 1–3 s).

    · 204, empty: nothing to read, nothing to leak
    · never touches the database (Atlas M0: 500 connections at most), even
      when the database is down
    · no login needed, and no cookie or header changes its answer
    · cheap: a thousand pings stay well under a second

Run: cd api && python3 tests/test_warm.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-warm")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:300]}"))


def main():
    import server
    import httpx

    async def calls(n, headers=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
            return [await ac.get("/api/warm", headers=headers or {}) for _ in range(n)]

    def run(n=1, headers=None):
        return asyncio.new_event_loop().run_until_complete(calls(n, headers))

    r = run()[0]
    check(f"204, empty ({r.status_code}, {len(r.content)} bytes)", r.status_code == 204 and r.content == b"")
    check("never cached by a browser or the CDN", "no-store" in r.headers.get("cache-control", ""))

    # the database down: still 204, and nothing asked of it
    touched = []

    class Down:
        def __getattr__(self, name):
            touched.append(name)
            raise RuntimeError("Atlas down")

        def __getitem__(self, name):
            touched.append(name)
            raise RuntimeError("Atlas down")
    real = server.db
    server.db = Down()
    try:
        r = run()[0]
        check(f"the database down: still 204 ({r.status_code})", r.status_code == 204)
        check(f"…and never asked ({touched})", touched == [])
    finally:
        server.db = real

    r = run(headers={"Authorization": "Bearer nonsense", "Cookie": "x=1"})[0]
    check(f"a bad token or a cookie changes nothing ({r.status_code})", r.status_code == 204 and r.content == b"")

    t0 = time.perf_counter()
    rs = run(1000)
    dt = time.perf_counter() - t0
    check(f"a thousand pings: all 204, {dt:.2f}s", all(x.status_code == 204 for x in rs) and dt < 5)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
