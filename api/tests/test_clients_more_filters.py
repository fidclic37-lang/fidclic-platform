"""
Clients › « Plus de filtres » (user, 2026-10-08): the old page's filters in
the new design — palier, visits, total spent, average basket, postal code,
notifications — on the list, the ids (« Contacter ») and the export alike.

Run: cd api && /usr/local/bin/python3 tests/test_clients_more_filters.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-more-filters")
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
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    people = [  # id, tier, visits, spent, postal
        ("a", "bronze", 1, 8.0, "37000"), ("b", "silver", 12, 180.0, "37100"), ("c", "gold", 25, 600.0, "37200"),
        ("d", "vip", 45, 2400.0, "75011"), ("e", "bronze", 0, 0.0, "06480"),
    ]
    for cid, tier, v, spent, pc in people:
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid.upper(), "tier": tier, "visits": v,
                                 "total_amount_paid": spent, "postal_code": pc, "created_at": now - dt.timedelta(days=200),
                                 "last_visit_date": now - dt.timedelta(days=3) if v else None})
    db.push_subscriptions.insert_many([{"tenant_id": "t1", "customer_id": "b", "endpoint": "x1"},
                                       {"tenant_id": "t1", "customer_id": "d", "endpoint": "x2"}])

    def get(path, **q):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(path, headers=H, params={"per_page": 50, **q})
        return asyncio.get_event_loop().run_until_complete(run())

    ids = lambda **q: sorted(r["id"] for r in get("/api/owner/clients/list", **q).json()["rows"])   # noqa: E731
    check("no extra filter: everyone", ids() == ["a", "b", "c", "d", "e"])
    check("palier Or", ids(tier="gold") == ["c"])
    check("visits between 10 and 30", ids(visits_min="10", visits_max="30") == ["b", "c"])
    check("total spent at least 500 €", ids(spent_min="500") == ["c", "d"])
    check("total spent at most 200 €, French comma accepted", ids(spent_max="200,00") == ["a", "b", "e"])
    check("average basket at least 20 € (never-came clients have none)", ids(basket_min="20") == ["c", "d"])
    check("postal code 37 = the whole département", ids(postal="37") == ["a", "b", "c"])
    check("postal code 37100 exactly", ids(postal="37100") == ["b"])
    check("notifications on", ids(notif="oui") == ["b", "d"])
    check("notifications off", ids(notif="non") == ["a", "c", "e"])
    check("they combine (and with the segment filters)", ids(postal="37", notif="non", visits_min="1") == ["a", "c"])
    r = get("/api/owner/clients/ids", tier="vip")
    check("« Contacter » gets exactly the filtered clients", r.json()["ids"] == ["d"])
    csv = get("/api/owner/clients/export", postal="37", tier="silver").text
    check("the export follows the filters", "\nB;" in csv and "\nA;" not in csv and "\nC;" not in csv)
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "silver"}})
    check("without « CRM avancé » in the plan, the extra filters are ignored (like the other refinements)",
          len(ids(tier="gold")) in (0, 5))
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "vip"}})
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "pages", "ClientsPage.jsx")).read()
    check("the page shows them in « Plus de filtres » and saves them with the filter",
          'label="Palier"' in src and 'label="Code postal (ou son début)"' in src and "...extraParams" in src
          and "setExtraState(Object.fromEntries(" in src)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
