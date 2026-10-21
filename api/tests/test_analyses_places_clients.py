"""
Analyses › Acquisition › Données géographiques (user, 2026-10-21): a click
on an area opens its clients on the Clients page — their details and every
action there — exactly the clients the bar counts.

Run: cd api && /usr/local/bin/python3 tests/test_analyses_places_clients.py
"""
import asyncio
import datetime as dt
import os
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-analyses-places")
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
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    cast = [("a", "37000", ""), ("b", "37000", ""), ("c", "37100", ""), ("d", "37100", ""), ("e", "37100", ""),
            ("f", "37540", ""), ("g", "", "Vouvray"), ("h", "", "")]
    for cid, pc, city in cast:
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": f"FT-{cid.upper()}",
                                 "postal_code": pc, "city": city, "visits": 1, "points": 0,
                                 "created_at": now - dt.timedelta(days=3)})

    def get(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=H)
        return asyncio.get_event_loop().run_until_complete(run()).json()

    places = get("/api/owner/analyses?tab=acquisition&days=7")["data"]["places"]
    check(f"every area bar carries its clients' link ({[p['name'] for p in places]})",
          places and all(p.get("segment") == f"place:{p['name']}" for p in places))
    total = 0
    for p in places:
        lst = get(f"/api/owner/clients/list?segment={quote(p['segment'])}&per_page=50")
        rows = lst.get("rows") or []
        total += len(rows)
        check(f"« {p['name']} »: the list has the bar's {p['count']} client(s) ({len(rows)})", len(rows) == p["count"])
    check(f"no client in two areas, none lost ({total} / {len(cast)})", total == len(cast))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
