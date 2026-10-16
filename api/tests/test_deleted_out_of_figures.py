"""
A deleted client leaves the counts — Dashboard, Analyses, Clients — but its
past visits and revenue stay (user, 2026-10-15 decision; 2026-10-16: deleted,
the dashboard and Analyses still counted it).

Run: cd api && /usr/local/bin/python3 tests/test_deleted_out_of_figures.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-deleted-figures")
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
    import features.wallet_passes as WP

    db = server.db
    WP.notify_passes = lambda *a, **k: {"sent": 0}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = datetime.now(timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "shop", "name": "Shop", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    for cid in ("a", "b", "c"):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": f"FT-DF0000{cid.upper()}0",
                                 "visits": 1, "points": 0, "total_amount_paid": 20.0, "created_at": now - timedelta(days=3)})
        db.visits.insert_one({"id": f"v{cid}", "tenant_id": "t1", "customer_id": cid, "amount_paid": 20.0,
                              "visit_time": now - timedelta(days=2)})

    def kpi(rows, key):
        return next((k["value"] for k in rows if k.get("key") == key), None)

    def figures():
        home = http("GET", "/api/owner/home/overview", headers=H).json()
        ana = http("GET", "/api/owner/analyses?tab=vue", headers=H).json()["data"]
        home_rows = home.get("cards") or []
        ana_rows = ana.get("strip") or []
        return kpi(home_rows, "clients"), kpi(ana_rows, "clients"), kpi(ana_rows, "revenue")

    before = figures()
    check(f"before: 3 clients on the dashboard and in Analyses ({before})", before[0] == 3 and before[1] == 3)
    r = http("POST", "/api/owner/clients/b/delete", headers=H)
    check("client b deleted", r.status_code == 200)
    after = figures()
    check(f"after: 2 clients on the dashboard ({after[0]})", after[0] == 2)
    check(f"…and in Analyses ({after[1]})", after[1] == 2)
    check(f"the revenue keeps its visit ({before[2]} → {after[2]})", after[2] == before[2])
    http("POST", "/api/owner/clients/b/restore", headers=H)
    check("restored: counted again", figures()[:2] == (3, 3))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
