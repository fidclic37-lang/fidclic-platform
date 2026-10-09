"""
QA F20 (2026-10-09): a negative visit amount. The till turned « -1 » into
« 1 » without a word; the server accepted a negative amount from anything
that sent one — the client's spend went down and, on a cashback card, points
were taken away. Now both refuse it, plainly.

Run: cd api && /usr/local/bin/python3 tests/test_scan_amount.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-scan-amount")
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

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"}),
         "Content-Type": "application/json"}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "cashback", "cashback_rate": 5,
                                  "reward_threshold_stamps": 10})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-AMOUNT01", "name": "Marie",
                             "visits": 3, "points": 100, "total_amount_paid": 60.0})

    def scan(raw):
        return http("POST", "/api/owner/scan", headers=H, content=raw)

    def state():
        c = db.customers.find_one({"id": "c1"})
        return c["visits"], c["points"], c["total_amount_paid"], db.visits.count_documents({"customer_id": "c1"})

    before = state()
    print("1. Refusé, et dit en clair")
    r = scan('{"barcode_id": "FT-AMOUNT01", "amount_paid": -1}')
    check(f"-1 € is refused ({r.status_code})", r.status_code == 400
          and r.json().get("detail") == "Le montant ne peut pas être négatif.")
    check("…nothing moved: no visit, spend and points unchanged (cashback card)", state() == before)
    r = scan('{"barcode_id": "FT-AMOUNT01", "amount_paid": -0.01}')
    check("even a cent below zero", r.status_code == 400)
    r = scan('{"barcode_id": "FT-AMOUNT01", "amount_paid": NaN}')
    check(f"not a number is refused ({r.status_code})", r.status_code in (400, 422) and state() == before)
    r = scan('{"barcode_id": "FT-AMOUNT01", "amount_paid": 250000}')
    check(f"an absurd amount is refused, like the merchant API ({r.status_code})",
          r.status_code == 400 and "trop élevé" in r.json().get("detail", "") and state() == before)

    print("\n2. Les montants normaux passent")
    r = scan('{"barcode_id": "FT-AMOUNT01", "amount_paid": 0}')
    check(f"0 € (a visit without a purchase) goes through ({r.status_code})", r.status_code == 200)
    r = scan('{"barcode_id": "FT-AMOUNT01", "amount_paid": 12.5}')
    v, p, spent, n = state()
    check("12,50 € adds spend and cashback", r.status_code == 200 and spent == 72.5 and p > 100 and n == 2)
    r = scan('{"barcode_id": "FT-AMOUNT01"}')
    check("no amount at all still means 0 €", r.status_code == 200)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
