"""
A cagnotte reads in euros everywhere (QA R7 F39, user 2026-10-20: « cashback
ko euros mein hi dikhao »): a 20 € purchase at 5 % credits 1,00 € — on the
Wallet pass (Apple and Google), in a message's {points}, and in the client's
fiche and its adjustment. The ledger stays in cents.

Run: cd api && /usr/local/bin/python3 tests/test_cashback_euros.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-cashback-euros")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)


def main():
    import server
    import auth
    import httpx
    import features.wallet_passes as WP

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "cashback", "cashback_rate": 5})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-CASH0001", "name": "Marie",
                             "visits": 0, "points": 0, "total_amount_paid": 0.0})

    r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": "FT-CASH0001", "amount_paid": 20})
    d = r.json()
    check(f"20 € at 5 % credits 100 cents ({r.status_code}, {d.get('points_earned')}, {d.get('programme')})",
          r.status_code == 200 and d.get("points_earned") == 100 and d.get("programme") == "cashback")
    cust = db.customers.find_one({"id": "c1"}, {"_id": 0})
    check("the ledger keeps cents", cust["points"] == 100)

    payload = server._serialize_card_payload(cust)
    pj = WP.build_pass_json(payload)
    sc = pj.get("storeCard") or pj.get("generic") or {}
    fields = [f for grp in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields")
              for f in sc.get(grp, []) if f.get("key") == "points"]
    f = fields[0] if fields else {}
    check(f"Apple: « CAGNOTTE » 1.0 EUR ({f.get('label')} {f.get('value')} {f.get('currencyCode')})",
          f.get("label") == "CAGNOTTE" and f.get("value") == 1.0 and f.get("currencyCode") == "EUR")
    check("…and its change message speaks of the cagnotte", "cagnotte" in (f.get("changeMessage") or "").lower())
    obj = WP._gw_object(payload)
    bal = (obj.get("loyaltyPoints") or {}).get("balance") or {}
    check(f"Google: a money balance of 1 € ({bal})", bal == {"money": {"micros": 1_000_000, "currencyCode": "EUR"}})

    check(f"a message's {{points}} reads « 1,00 € » ({server.render_template('Votre cagnotte : {points}', cust)})",
          server.render_template("Votre cagnotte : {points}", cust) == "Votre cagnotte : 1,00 €")

    fiche = http("GET", "/api/owner/clients/c1/fiche", headers=H).json()
    check(f"the fiche knows it is a cagnotte ({fiche.get('programme')})", fiche.get("programme") == "cashback")
    r = http("POST", "/api/owner/clients/c1/ajustement", headers=H, json={"points": 150, "visits": 0, "reason": "geste"})
    check(f"an adjustment says euros ({r.json().get('text')})", r.status_code == 200 and "+1,50 € de cagnotte" in r.json().get("text", ""))
    r = http("POST", "/api/owner/clients/c1/ajustement", headers=H, json={"points": -1000, "visits": 0, "reason": "erreur"})
    check(f"…and so does its refusal ({r.json().get('detail')})", r.status_code == 400 and "2,50 €" in str(r.json().get("detail")))

    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"programme": "points_euro", "points_per_euro": 2}})
    cust = db.customers.find_one({"id": "c1"}, {"_id": 0})
    f = next(f for grp in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields")
             for f in ((WP.build_pass_json(server._serialize_card_payload(cust)).get("storeCard") or {}).get(grp, []))
             if f.get("key") == "points")
    check("a points card stays in points", "currencyCode" not in f and f.get("value") == 250)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
