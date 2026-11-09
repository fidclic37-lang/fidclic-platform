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
    from services import communes
    from features import analyses as AN

    # The commune name comes from the Base Adresse Nationale. A test must not
    # depend on the network: on a laptop the call fails, on the CI it answers —
    # or times out once and answers the next time (2026-11-09, PR #454: the bar
    # said « 37540 », the list a moment later looked for « Saint-Cyr-sur-Loire »).
    BAN = {"37540": "Saint-Cyr-sur-Loire"}            # postal code → commune; anything else: unreachable
    communes._fetch = lambda postal: BAN.get(postal, "")

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
    check("37540 is named by its commune", "Saint-Cyr-sur-Loire" in [p["name"] for p in places])

    # The address service is down while the bar is drawn, and back by the click:
    # the bar says the bare code, the list must still find its clients.
    late = {"id": "z", "tenant_id": "t1", "postal_code": "37230", "city": ""}
    bar = AN._place_of(late)[0]
    check(f"service down: the bar is the bare code ({bar})", bar == "37230")
    BAN["37230"] = "Fondettes"
    check("service back: the client now reads « Fondettes »", AN._place_of(late)[0] == "Fondettes")
    check("…and the « 37230 » bar still lists them", AN.place_matches(late, "37230"))
    check("…and the « Fondettes » bar too", AN.place_matches(late, "Fondettes"))
    check("a bare code never pulls in another code's client",
          not AN.place_matches({"postal_code": "37100", "city": ""}, "37230"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
