"""
« Historique d'achats » in Clients (user, 2026-10-15): for one client, every
visit — day and hour, establishment, products with quantities, amount, what
the card got — and the totals. Only for whoever may see that client.

Run: cd api && /usr/local/bin/python3 tests/test_client_purchases.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-client-purchases")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True}, {"id": "pal", "name": "PALISSY"}]},
        {"id": "t2", "slug": "other", "name": "Other", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Gabin", "barcode_id": "FT-GABIN001", "branch_id": "lib", "visits": 3},
        {"id": "c2", "tenant_id": "t1", "name": "Hugo", "barcode_id": "FT-HUGO0001", "branch_id": "pal", "visits": 0},
    ])
    now = dt.datetime(2026, 10, 14, 16, 30, tzinfo=dt.timezone.utc)
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "branch_id": "lib", "amount_paid": 29.0, "points_awarded": 0,
         "stamps_awarded": 1, "visit_time": now - dt.timedelta(days=10),
         "items": [{"item_id": "i1", "name": "Coupe + barbe", "price": 29, "qty": 1, "line_total": 29.0}]},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c1", "branch_id": "pal", "amount_paid": 37.0, "points_awarded": 0,
         "stamps_awarded": 1, "visit_time": now,
         "items": [{"item_id": "i2", "name": "Coupe", "price": 22, "qty": 1, "line_total": 22.0},
                   {"item_id": "i3", "name": "Barbe express", "price": 15, "qty": 1, "line_total": 15.0}]},
        {"id": "v3", "tenant_id": "t1", "customer_id": "c1", "branch_id": "lib", "amount_paid": 12.0, "points_awarded": 0,
         "visit_time": now - dt.timedelta(days=3)},
    ])
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"email": "p@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True, "branch_ids": ["pal"]},
        {"email": "s@x.fr", "role": "staff", "tenant_id": "t1", "active": True},
        {"email": "z@x.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
    ])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731

    print("1. What the owner sees")
    r = http("GET", "/api/owner/clients/c1/purchases", headers=tok("o@x.fr", "business_owner"))
    d = r.json()
    check(f"answered ({r.status_code})", r.status_code == 200)
    check(f"totals: 3 visits, 78 € spent, 26 € average ({d.get('totals')})",
          d["totals"]["visits"] == 3 and d["totals"]["spent"] == 78.0 and d["totals"]["average"] == 26.0)
    check("newest first, with the day and hour", [x["id"] for x in d["rows"]] == ["v2", "v3", "v1"]
          and d["rows"][0]["at"].startswith("2026-10-14T16:30"))
    check("products with quantities and line totals", d["rows"][0]["items"] == [
        {"name": "Coupe", "qty": 1, "total": 22.0}, {"name": "Barbe express", "qty": 1, "total": 15.0}])
    check("the establishment where it was scanned", d["rows"][0]["store"] == "PALISSY" and d["rows"][2]["store"] == "LIBERTÉ")
    check("an amount typed without products: no lines, the amount", d["rows"][1]["items"] == [] and d["rows"][1]["amount"] == 12.0)
    check(f"the card's unit and what each visit gave ({d['unit']})", d["unit"] == "stamps" and d["rows"][0]["stamps"] == 1)
    r = http("GET", "/api/owner/clients/c1/purchases", headers=tok("o@x.fr", "business_owner"), params={"per_page": 2, "page": 2})
    check("pages: the last one holds the oldest", r.json()["pages"] == 2 and [x["id"] for x in r.json()["rows"]] == ["v1"])
    e = http("GET", "/api/owner/clients/c2/purchases", headers=tok("o@x.fr", "business_owner")).json()
    check("a client with no purchase: empty, zero", e["rows"] == [] and e["totals"]["visits"] == 0 and e["totals"]["average"] == 0)

    print("\n2. Only whoever may see the client")
    # a client is a store's when they signed up or were scanned there (store_scope)
    db.customers.insert_one({"id": "c3", "tenant_id": "t1", "name": "Inès", "barcode_id": "FT-INES0001", "branch_id": "lib", "visits": 0})
    check("a PALISSY administrateur, a LIBERTÉ-only client: refused",
          http("GET", "/api/owner/clients/c3/purchases", headers={**tok("p@x.fr", "administrateur"), "X-FidClic-Store": "pal"}).status_code in (403, 404))
    check("…a client scanned at PALISSY too: yes",
          http("GET", "/api/owner/clients/c1/purchases", headers={**tok("p@x.fr", "administrateur"), "X-FidClic-Store": "pal"}).status_code == 200)
    check("…its own client: yes",
          http("GET", "/api/owner/clients/c2/purchases", headers={**tok("p@x.fr", "administrateur"), "X-FidClic-Store": "pal"}).status_code == 200)
    check("staff: refused", http("GET", "/api/owner/clients/c1/purchases", headers=tok("s@x.fr", "staff")).status_code == 403)
    check("another account: not found", http("GET", "/api/owner/clients/c1/purchases", headers=tok("z@x.fr", "business_owner", "t2")).status_code == 404)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
