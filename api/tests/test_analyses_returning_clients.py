"""
Analyses › Fidélisation (user, 2026-10-21): « Clients revenus » and « Taux
de retour » open those very clients on the Clients page — their details and
every action there — with the same rule as the figure (2 visits or more).
« Clients fidélisés » opens the fidèles. The empty « Avis clients » tab says
how reviews really arrive (no switch to turn on).

Run: cd api && /usr/local/bin/python3 tests/test_analyses_returning_clients.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-analyses-returning")
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
    for i, v in enumerate([0, 1, 1, 2, 3, 5, 9]):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "name": f"Client {i}", "barcode_id": f"FT-C{i}",
                                 "visits": v, "points": 0, "created_at": now - dt.timedelta(days=40),
                                 "last_visit_date": now - dt.timedelta(days=2)})
    db.customers.insert_one({"id": "gone", "tenant_id": "t1", "name": "Supprimé", "barcode_id": "FT-GONE", "visits": 4,
                             "created_at": now - dt.timedelta(days=40), "deleted_at": now})

    def get(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=H)
        return asyncio.get_event_loop().run_until_complete(run()).json()

    tab = get("/api/owner/analyses?tab=fidelisation&days=7")["data"]
    by = {s["key"]: s for s in tab["strip"]}
    check(f"« Clients revenus » = 4 ({by['returning']['value']})", by["returning"]["value"] == 4)
    check("…opens its clients", by["returning"].get("to") == "/dashboard/customers?segment=returning")
    check("« Taux de retour » opens the same clients", by["retention"].get("to") == "/dashboard/customers?segment=returning")
    check("« Clients fidélisés » opens the fidèles", by["loyal"].get("to") == "/dashboard/customers?segment=loyal")

    lst = get("/api/owner/clients/list?segment=returning&per_page=50")
    rows = lst.get("rows") or lst.get("clients") or []
    ids = sorted(r["id"] for r in rows)
    check(f"the Clients page lists exactly those 4 ({ids})", ids == ["c3", "c4", "c5", "c6"])
    check("…the figure and the list agree", len(ids) == by["returning"]["value"])
    check("…a deleted client is in neither", "gone" not in ids)

    avis = get("/api/owner/analyses?tab=avis&days=7")["data"]
    check(f"no reviews: the tab says how they arrive ({avis.get('message', '')[:60]}…)",
          avis.get("empty") and "Donner mon avis" in avis.get("message", ""))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
