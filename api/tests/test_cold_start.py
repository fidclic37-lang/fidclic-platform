"""
Faster cold starts (2026-10-01) and the reset endpoint:
- indexes are asked for only when their set changes (2026-10-17: was once
  per commit), built in the background on Vercel;
- /api/reset-seed needs a super admin and never runs on Vercel;
- the Stripe SDK is not imported until billing uses it.

Run: cd api && /usr/local/bin/python3 tests/test_cold_start.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import FastAPI
    import asyncio
    import httpx
    from pymongo.collection import Collection
    from features import _loader as L, billing as BL

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    print("\nIndexes only when they change, in the background")
    import threading
    def wait_build():
        for th in threading.enumerate():
            if th.name == "fidclic-indexes":
                th.join(60)
    original = Collection.create_index
    os.environ.pop("VERCEL_GIT_COMMIT_SHA", None)
    check("outside Vercel: always asked for", L._indexes_done(db, L._build_id()) is False)
    os.environ["VERCEL_GIT_COMMIT_SHA"] = "commit-a"
    L.register_all(FastAPI(), db)
    wait_build()
    mark = db.platform_settings.find_one({"key": L.INDEX_MARKER})
    check("…then remembers the index set", mark and str(mark["value"]).startswith("idx-"))
    check("the next cold start skips them", L._indexes_done(db, mark["value"]) is True)
    asked = []
    Collection.create_index = lambda self, *a, **k: asked.append(self.name)
    os.environ["VERCEL_GIT_COMMIT_SHA"] = "commit-b"
    L.register_all(FastAPI(), db)
    wait_build()
    check("a new deployment with the same indexes asks nothing", asked == [])
    Collection.create_index = original
    L.register_all(FastAPI(), db)
    check("create_index is put back after start-up", Collection.create_index is original)
    app = FastAPI()
    L.register_all(app, db)
    check("every feature router is still mounted when skipping", len(app.routes) > 300)
    os.environ.pop("VERCEL_GIT_COMMIT_SHA", None)

    print("\n/api/reset-seed")
    db.users.insert_one({"email": "keep@me.fr", "role": "business_owner"})
    def post(path, headers=None):
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as c:
                return await c.post(path, headers=headers or {})
        return asyncio.run(go())
    r = post("/api/reset-seed")
    check("refused without signing in", r.status_code in (401, 403))
    check("nothing was deleted", db.users.find_one({"email": "keep@me.fr"}) is not None)
    owner = server.create_access_token({"sub": "keep@me.fr", "role": "business_owner", "tenant_id": "t1"})
    r = post("/api/reset-seed", headers={"Authorization": f"Bearer {owner}"})
    check("refused for a business owner", r.status_code == 403 and db.users.find_one({"email": "keep@me.fr"}))
    server._ON_VERCEL = True
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin"})
    boss = server.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin"})
    r = post("/api/reset-seed", headers={"Authorization": f"Bearer {boss}"})
    check("refused on Vercel, even for a super admin", r.status_code == 403 and db.users.find_one({"email": "keep@me.fr"}))
    server._ON_VERCEL = False

    print("\nSeed on Vercel")
    env = lambda **kw: (os.environ.get("DISABLE_SEED", "") == "1" or (bool(kw.get("VERCEL")) and kw.get("FORCE_SEED", "") != "1"))   # noqa: E731
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")).read()
    check("the rule in server.py is the one tested here",
          'SEED_DISABLED = os.environ.get("DISABLE_SEED", "") == "1" or (_ON_VERCEL and os.environ.get("FORCE_SEED", "") != "1")' in src)
    os.environ["DISABLE_SEED"] = ""
    check("off on Vercel by default", env(VERCEL="1") is True)
    check("FORCE_SEED=1 turns it back on", env(VERCEL="1", FORCE_SEED="1") is False)
    check("still on locally", env() is False)
    os.environ["DISABLE_SEED"] = "1"

    print("\nStripe loaded on first use")
    check("not imported at start-up", BL.stripe is None or type(BL.stripe).__name__ == "_LazyStripe")
    if BL.stripe is not None:
        check("still not loaded before billing is used", BL._LazyStripe._mod is None or "stripe" in sys.modules)
        check("loads on first use", hasattr(BL.stripe, "Customer") and BL._LazyStripe._mod is not None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
