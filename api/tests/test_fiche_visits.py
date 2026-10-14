"""
« Modifier la fiche » says how often the client comes (QA BUG-005, user
2026-10-13: « Haan, fiche mein bhi »): « 12 visites · dernière le 10/10 »,
read only — the Clients list already had the column (#216).

Run: cd api && /usr/local/bin/python3 tests/test_fiche_visits.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-fiche-visits")
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
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    last = dt.datetime(2026, 10, 10, 9, 30, tzinfo=dt.timezone.utc)
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Marie", "visits": 12, "last_visit_date": last, "barcode_id": "FT-MARIE001"},
        {"id": "c2", "tenant_id": "t1", "name": "Léo", "visits": 0, "barcode_id": "FT-LEO00001"},
    ])
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def fiche(cid):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(f"/api/owner/clients/{cid}/fiche", headers=H)
        return asyncio.get_event_loop().run_until_complete(run()).json()["client"]

    m = fiche("c1")
    check(f"12 visits and the last one's date ({m.get('visits')}, {m.get('last_visit')})",
          m["visits"] == 12 and m["last_visit"].startswith("2026-10-10T09:30"))
    l = fiche("c2")
    check(f"never came: 0, no date ({l.get('visits')}, {l.get('last_visit')})", l["visits"] == 0 and l["last_visit"] is None)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
