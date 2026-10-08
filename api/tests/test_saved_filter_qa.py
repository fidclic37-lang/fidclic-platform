"""
QA F01 (2026-10-08): « Enregistrer ce filtre » crashed the Clients page — the
page sent its segment KEY where the server expected a rule object, got a 422,
and rendered the error object. The key is now accepted and kept in the
filters; the page no longer sends it there.

Run: cd api && /usr/local/bin/python3 tests/test_saved_filter_qa.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-saved-filter")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "s", "name": "S", "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    filters = {"segment": "loyal", "status": "", "spend": "", "joined": "", "search": "", "sort": "recent", "source": ""}
    r = http("POST", "/api/owner/segments", headers=H, json={"name": "Fidèles", "filters": filters})
    check(f"what the page sends now is saved ({r.status_code})", r.status_code == 200 and r.json()["filters"]["segment"] == "loyal")
    r = http("POST", "/api/owner/segments", headers=H, json={"name": "Ancien", "segment": "inactive",
                                                             "filters": {"status": ""}})
    check(f"what an older page sent (segment as a key) is saved too, not refused ({r.status_code})",
          r.status_code == 200 and r.json()["filters"]["segment"] == "inactive" and r.json()["segment"] is None)
    r = http("POST", "/api/owner/segments", headers=H, json={"name": "Règle", "segment": {"rules": []}, "filters": {}})
    check("a rule object still works", r.status_code == 200 and r.json()["segment"] == {"rules": []})
    rows = http("GET", "/api/owner/segments", headers=H).json()["segments"]
    check("all three are listed", len(rows) == 3)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
