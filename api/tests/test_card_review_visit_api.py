"""
« Donner mon avis » on the card page (Mon compte) opens only after a recent
visit: the page reads customer.last_visit_date / last_visit_id, and GET
/api/card/{bc} never sent them — the section never showed (2026-11-25).

Through the real HTTP endpoints on the mongomock server:

  GET  /api/card/{bc}         + customer.last_visit_date (ISO UTC, Z)
                              + customer.last_visit_id   (this client's newest visit)
  POST /api/public/reviews    one review per visit, with that id

Run: cd api && python3 tests/test_card_review_visit_api.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-review-visit")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import auth
    import server
    import httpx
    from features import card_page as CPG
    from services import card_owner as CO

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def login(role, tenant):
        email = f"{role}-{tenant}@x.fr"
        db.users.update_one({"email": email}, {"$set": {"email": email, "role": role, "tenant_id": tenant}}, upsert=True)
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tenant})}

    now = datetime.now(timezone.utc).replace(microsecond=0)
    ago = lambda **kw: now - timedelta(**kw)   # noqa: E731
    z = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "DEMO ONE", "is_active": True, "plan": "vip",
                           "subscription_status": "active",
                           "branches": [{"id": "main", "name": "CENTRE", "is_main": True}, {"id": "pal", "name": "GARE"}]})
    db.tenants.insert_one({"id": "t2", "slug": "gs", "name": "DEMO TWO", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db["card_templates"]._real.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps",
                                           "reward_threshold_stamps": 10})

    def cust(cid, tid, name, branch="main", **kw):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": name, "email": f"{cid}@x.fr",
                                 "phone": "0611111111", "visits": 3, "points": 0, "branch_id": branch, **kw})
        return bc

    BC = cust("marie", "t1", "Marie Dupont", last_visit_date=ago(days=3))
    BC_NEW = cust("neo", "t1", "Néo Sansvisite")                         # signed up, never scanned
    BC_OLD = cust("olga", "t1", "Olga Legacy", last_visit_date=ago(days=2))   # old data: no visit row
    BC_FAR = cust("fred", "t1", "Fred Loin", last_visit_date=ago(days=40))
    BC_STR = cust("sam", "t1", "Sam Texte")
    cust("paul", "t1", "Paul Martin")
    OWN = {"X-Card-Key": CO.key_for(BC)}
    key = lambda bc: {"X-Card-Key": CO.key_for(bc)}   # noqa: E731

    db.visits.insert_many([
        {"id": "v-old", "tenant_id": "t1", "customer_id": "marie", "branch_id": "main", "visit_time": ago(days=9)},
        {"id": "v-last", "tenant_id": "t1", "customer_id": "marie", "branch_id": "pal", "visit_time": ago(days=3)},
        # newer rows that are NOT Marie's visit at this shop
        {"id": "v-paul", "tenant_id": "t1", "customer_id": "paul", "visit_time": ago(hours=1)},
        {"id": "v-t2", "tenant_id": "t2", "customer_id": "marie", "visit_time": ago(hours=2)},
        {"id": "v-fred", "tenant_id": "t1", "customer_id": "fred", "visit_time": ago(days=40)},
        {"id": "v-sam", "tenant_id": "t1", "customer_id": "sam", "visit_time": "2026-11-20T09:15:00+01:00"},
    ])
    db.visits_cancelled.insert_one({"id": "v-cancel", "tenant_id": "t1", "customer_id": "marie",
                                    "visit_time": ago(hours=3), "cancelled_at": ago(hours=3)})

    print("1. Unit — card_page.last_visit(cust)")
    m = db.customers.find_one({"id": "marie"})
    check(f"the newest visit of this client at this shop ({CPG.last_visit(m)})",
          CPG.last_visit(m) == {"last_visit_date": z(ago(days=3)), "last_visit_id": "v-last"})
    check("never scanned → both None",
          CPG.last_visit(db.customers.find_one({"id": "neo"})) == {"last_visit_date": None, "last_visit_id": None})
    check("old data with no visit row → the customer's own date, no id",
          CPG.last_visit(db.customers.find_one({"id": "olga"})) == {"last_visit_date": z(ago(days=2)),
                                                                     "last_visit_id": None})
    check(f"a visit time saved as text → ISO UTC with Z ({CPG.last_visit(db.customers.find_one({'id': 'sam'}))})",
          CPG.last_visit(db.customers.find_one({"id": "sam"}))["last_visit_date"] == "2026-11-20T08:15:00Z")
    check("a customer without id/tenant → both None, no crash",
          CPG.last_visit({}) == {"last_visit_date": None, "last_visit_id": None})
    check("None → both None", CPG.last_visit(None) == {"last_visit_date": None, "last_visit_id": None})

    print("2. GET /api/card/{bc} sends them")
    r = http("GET", f"/api/card/{BC}", headers=OWN)
    c = r.json().get("customer", {})
    check(f"200 ({r.status_code})", r.status_code == 200)
    check(f"last_visit_id = Marie's newest visit here ({c.get('last_visit_id')})", c.get("last_visit_id") == "v-last")
    check(f"last_visit_date = that visit, ISO with Z ({c.get('last_visit_date')})",
          c.get("last_visit_date") == z(ago(days=3)))
    raw = r.text
    for leak in ("v-paul", "v-t2", "v-cancel", "v-old", "v-fred"):
        check(f"no other row leaks ({leak})", leak not in raw)
    n = http("GET", f"/api/card/{BC_NEW}", headers=key(BC_NEW)).json()["customer"]
    check(f"a card never scanned: both null ({n.get('last_visit_date')}, {n.get('last_visit_id')})",
          "last_visit_date" in n and n["last_visit_date"] is None and n.get("last_visit_id") is None)
    o = http("GET", f"/api/card/{BC_OLD}", headers=key(BC_OLD)).json()["customer"]
    check("old data: the date from the customer, no id", o.get("last_visit_date") == z(ago(days=2))
          and o.get("last_visit_id") is None)
    f = http("GET", f"/api/card/{BC_FAR}", headers=key(BC_FAR)).json()["customer"]
    check("a visit 40 days ago is still sent as it is (the page decides)", f.get("last_visit_date") == z(ago(days=40)))
    s = http("GET", f"/api/card/{BC_STR}", headers=key(BC_STR)).json()["customer"]
    check("a text visit time comes out as ISO Z", s.get("last_visit_date") == "2026-11-20T08:15:00Z")

    print("3. Who may read them — unchanged")
    check("no key → 403", http("GET", f"/api/card/{BC}").status_code == 403)
    check("another card's key → 403", http("GET", f"/api/card/{BC}", headers=key(BC_NEW)).status_code == 403)
    check("another business's owner → 403",
          http("GET", f"/api/card/{BC}", headers=login("business_owner", "t2")).status_code == 403)
    ow = http("GET", f"/api/card/{BC}", headers=login("business_owner", "t1"))
    check("the shop's owner sees the same date/id", ow.status_code == 200 and ow.json()["customer"]["last_visit_id"] == "v-last")

    print("4. The review for that visit")
    body = {"barcode_id": BC, "rating": 9, "text": "Top", "visit_id": c.get("last_visit_id")}
    r1 = http("POST", "/api/public/reviews", headers=OWN, json=body)
    check(f"first review of the visit → 200 ({r1.status_code})", r1.status_code == 200)
    saved = db.reviews.find_one({"customer_id": "marie"})
    check("saved with the visit id", saved and saved.get("visit_id") == "v-last")
    r2 = http("POST", "/api/public/reviews", headers=OWN, json=body)
    check(f"a second review of the same visit → 409 ({r2.status_code})", r2.status_code == 409)
    r3 = http("POST", "/api/public/reviews", headers=key(BC_NEW), json={**body, "visit_id": "v-other"})
    check(f"by card number, the card's own key only: Néo cannot use Marie's card ({r3.status_code})",
          r3.status_code == 403)

    print("5. A new scan moves them")
    db.visits.insert_one({"id": "v-new", "tenant_id": "t1", "customer_id": "marie", "visit_time": ago(minutes=5)})
    c2 = http("GET", f"/api/card/{BC}", headers=OWN).json()["customer"]
    check(f"the newest visit wins ({c2.get('last_visit_id')})", c2.get("last_visit_id") == "v-new"
          and c2.get("last_visit_date") == z(ago(minutes=5)))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
