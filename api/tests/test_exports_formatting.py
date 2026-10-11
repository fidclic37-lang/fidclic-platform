"""
Exports and amounts — QA 2026-10-08:
  F13  the clients CSV cut the UTC date: a 00:30 visit in Paris showed the day before
  F14  a 0 € visit was blank in the history CSV
  F15  « Panier moyen » differed between Insights and Analyses (see insights tests)
  and amounts read « 145.33 € », « 15,5 € », « 93,1 € ».

Run: cd api && /usr/local/bin/python3 tests/test_exports_formatting.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-exports")
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
    from features import insights_page as I, segmentation as SEG
    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "Café", "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    # 23:30 UTC on 7 October = 01:30 in Paris on 8 October
    late = dt.datetime(2026, 10, 7, 23, 30, tzinfo=dt.timezone.utc)
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Noctambule", "barcode_id": "FT-0000000C",
                             "visits": 2, "total_amount_paid": 12.5, "last_visit_date": late,
                             "created_at": dt.datetime(2026, 9, 30, 22, 15, tzinfo=dt.timezone.utc)})
    now = dt.datetime.now(dt.timezone.utc)
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 0.0, "points_awarded": 10, "visit_time": now - dt.timedelta(hours=2)},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 12.5, "points_awarded": 10, "visit_time": now - dt.timedelta(hours=1)},
    ])

    def get(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=H)
        return asyncio.get_event_loop().run_until_complete(run())

    print("\nExport clients (F13)")
    body = get("/api/owner/clients/export").text
    row = next(l for l in body.splitlines() if l.startswith("Noctambule"))
    check(f"the last visit is the day in Paris, 08/10/2026 ({row})", "08/10/2026" in row and "2026-10-07" not in row)
    check("the sign-up too: 22:15 UTC on 30/09 is 01/10 in Paris", "01/10/2026" in row)

    print("\nExport historique (F14)")
    body = get("/api/owner/history/export").text
    lines = [l for l in body.splitlines() if "Noctambule" in l]
    check(f"a 0 € visit says 0,00 — not blank ({lines})", any(l.endswith(";0,00") for l in lines))
    check("and 12,50 stays 12,50", any(l.endswith(";12,50") for l in lines))
    act = get("/api/owner/history/activity").json()
    rows = act.get("rows") or act.get("items") or []
    check("the history page gets 0, not nothing", any(r.get("amount") == 0 for r in rows))

    print("\nLes montants")
    check("Insights: 15,50 € (not « 15,5 € »)", I._eur_cents(15.5) == "15,50 €")
    check("Segmentation: 145,33 € (not « 145.33 € »)", SEG._eur(145.33) == "145,33 €")
    check("a whole amount has no cents, and thousands are spaced", SEG._eur(1200) == "1 200 €" and I._eur_cents(1200) == "1 200 €")
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "lib", "money.js")).read()
    check("the pages share one formatter that keeps two cent digits", "minimumFractionDigits: cents ? 2 : 0" in src)
    for page in ("DashboardHomePage.jsx", "AnalysesPage.jsx"):
        s = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "pages", page)).read()
        check(f"{page} uses it", "const money = eur;" in s)
    s = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "pages", "CampagnesPage.jsx")).read()
    check("CampagnesPage.jsx uses it", "import { eur } from '../lib/money';" in s and "eur(s.value)" in s)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
