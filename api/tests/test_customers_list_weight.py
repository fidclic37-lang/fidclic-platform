"""
GET /api/owner/customers went out whole (2026-11-12, measured in production:
1.4 MB for 828 clients — every field of every document, no pagination). The
campaign composer asked for it on each search keystroke, and the « aperçu »
asked for ALL of it to use one row. On Atlas M0 that spends the 10 GB/week
budget for nothing, and on a phone it is seconds.

Now the list is SLIM (only the fields its pages read — never the brain's
fields, notes, tokens or other internals), sorted newest first, and takes
`limit` + `offset` (applied after the filters, with X-Total-Count saying how
many matched). Without `limit` the whole (slim) list still comes: the saved
segments, CSV export and legacy analytics keep working unchanged.

Run: cd api && python3 -u tests/test_customers_list_weight.py
"""
import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-customers-weight")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0
UTC = dt.timezone.utc

ALLOWED = {"id", "barcode_id", "name", "email", "phone", "tier", "visits", "points", "total_amount_paid",
           "acquisition_source", "postal_code", "city", "created_at", "join_date", "member_since",
           "last_visit_date", "pass_issued", "branch_id", "birthday"}
SECRET_MARKERS = ("owner_key", "brain", "notes", "geo_pass_key", "points_news", "ai_", "totp", "password")


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    import server
    import auth
    import httpx

    db = server.db
    NOW = dt.datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "Shop", "plan": "vip", "is_active": True,
                           "subscription_status": "active"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1", "active": True}])
    heavy = {"notes": "x" * 500, "geo_pass_key": "k" * 60, "points_news": {"title": "y" * 200},
             "brain_profile": {"rhythm": [1] * 50}, "owner_key": "secret-okey", "ai_memo": "z" * 300}
    for i in range(60):
        db.customers.insert_one({
            "id": f"c{i}", "tenant_id": "t1", "barcode_id": f"FT-W{i:06d}", "name": f"Client {i}",
            "email": f"c{i}@mail.fr", "phone": f"06000000{i:02d}", "tier": ["bronze", "silver", "gold"][i % 3],
            "visits": i % 9, "points": i, "total_amount_paid": float(i * 7), "acquisition_source": "qr_store",
            "postal_code": "37000", "city": "Tours", "created_at": NOW - dt.timedelta(days=i),
            "last_visit_date": NOW - dt.timedelta(days=i % 20), **heavy})
    OWNER = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    STAFF = {"Authorization": "Bearer " + auth.create_access_token({"sub": "s@x.fr", "role": "staff", "tenant_id": "t1"})}
    URL = "/api/owner/customers"

    # ------------------------------------------------------------------ slim
    print("La liste est maigre")
    r = http("GET", URL, headers=OWNER)
    rows = r.json()
    check("still a plain list (nothing breaks)", r.status_code == 200 and isinstance(rows, list) and len(rows) == 60,
          (r.status_code, type(rows).__name__, len(rows) if isinstance(rows, list) else None))
    extra = sorted({k for c in rows for k in c} - ALLOWED)
    check("only the fields the pages read — nothing else", not extra, extra[:8])
    check("none of the internals leak (brain, notes, keys…)",
          not any(m in k for c in rows for k in c for m in SECRET_MARKERS))
    check("the fields the pages need are all there",
          {"id", "name", "visits", "total_amount_paid", "created_at", "barcode_id", "last_visit_date"} <= set(rows[0]))
    weight = len(r.content)
    check(f"60 clients weigh ~{weight // 1024} KB, not ~100 KB (full docs)", weight < 25 * 1024, weight)
    check("newest first (a stable order)", [c["id"] for c in rows[:3]] == ["c0", "c1", "c2"], [c["id"] for c in rows[:3]])

    # ------------------------------------------------------------------ limit / offset
    print("\nlimit et offset")
    r = http("GET", URL, headers=OWNER, params={"limit": 1})
    check("limit=1 → one row (the composer's « aperçu »)", len(r.json()) == 1 and r.json()[0]["id"] == "c0", r.json()[:1])
    check("…X-Total-Count says how many matched in all", r.headers.get("x-total-count") == "60", dict(r.headers))
    a = http("GET", URL, headers=OWNER, params={"limit": 25}).json()
    b = http("GET", URL, headers=OWNER, params={"limit": 25, "offset": 25}).json()
    c3 = http("GET", URL, headers=OWNER, params={"limit": 25, "offset": 50}).json()
    ids = [x["id"] for x in a + b + c3]
    check("three pages: 25 + 25 + 10, no repeat, no hole", len(ids) == 60 and len(set(ids)) == 60, (len(a), len(b), len(c3)))
    r = http("GET", URL, headers=OWNER, params={"tier": "gold", "limit": 5})
    check("limit comes AFTER the filters", len(r.json()) == 5 and all(x["tier"] == "gold" for x in r.json())
          and r.headers.get("x-total-count") == "20", (len(r.json()), r.headers.get("x-total-count")))
    r = http("GET", URL, headers=OWNER, params={"search": "Client 1", "limit": 25})
    check("search + limit (the composer's keystroke): ≤ 25 rows, the count told",
          len(r.json()) == 11 and r.headers.get("x-total-count") == "11", (len(r.json()), r.headers.get("x-total-count")))
    r = http("GET", URL, headers=OWNER, params={"offset": 55})
    check("offset without limit: the tail", [x["id"] for x in r.json()] == [f"c{i}" for i in range(55, 60)], r.json()[:2])

    # refused values
    for params, label in [({"limit": 0}, "limit=0"), ({"limit": -3}, "a negative limit"),
                          ({"limit": 5000}, "a limit over 500"), ({"offset": -1}, "a negative offset"),
                          ({"limit": "abc"}, "a limit that is not a number")]:
        code = http("GET", URL, headers=OWNER, params=params).status_code
        check(f"{label} → refused (422)", code == 422, code)

    # ------------------------------------------------------------------ filters still work on the slim list
    print("\nLes filtres d'avant tiennent")
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 5, "visits_per_stamp": 1})
    r = http("GET", URL, headers=OWNER, params={"cards_filled": "true"})
    check("cards_filled still computed", r.status_code == 200 and all(x["visits"] >= 5 for x in r.json()) and r.json())
    r = http("GET", URL, headers=OWNER, params={"min_avg_ticket": 7})
    check("min_avg_ticket still computed", r.status_code == 200 and r.json()
          and all((x["total_amount_paid"] / max(x["visits"], 1)) >= 7 for x in r.json()))
    r = http("GET", URL, headers=OWNER, params={"has_wallet_pass": "false", "limit": 10})
    check("wallet filter + limit together", r.status_code == 200 and len(r.json()) == 10)

    # ------------------------------------------------------------------ rights
    print("\nDroits")
    check("a till account (staff) still cannot read the list", http("GET", URL, headers=STAFF).status_code == 403)
    check("no token: refused", http("GET", URL).status_code in (401, 403))

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
