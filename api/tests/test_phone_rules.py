"""
Signup forms (user, 2026-10-09):
  • phone: digits only (« # », « * », letters got through); France 0 + exactly
    9 digits; abroad « + » and a country code from the list — on the customer
    signup, the business signup, « Modifier la fiche » and the merchant API;
  • postal code: 5 digits, text refused;
  • one e-mail = one customer per shop (QA F16);
  • the public page never hands over a card it did not create: typing someone
    else's number used to open THEIR card, owner key included.

Run: cd api && /usr/local/bin/python3 tests/test_phone_rules.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-phone-rules")
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
    from fastapi import HTTPException
    from services import customer_fields as CF
    from services.dial_codes import DIAL_CODES

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def ok(v):
        try:
            return CF.phone(v)
        except HTTPException:
            return None

    print("1. La règle du téléphone")
    check("06 12 34 56 78 → 0612345678", ok("06 12 34 56 78") == "0612345678")
    check("France written « +33 », « 0033 », « +33 0… » → the same 0612345678",
          ok("+33 6 12 34 56 78") == ok("0033612345678") == ok("+33 06 12 34 56 78") == "0612345678")
    check("abroad: +44 7700 900123 → +447700900123", ok("+44 7700 900123") == "+447700900123")
    check("« # », « * », letters are refused", ok("06#1234567") is None and ok("0612*45678") is None and ok("06abc45678") is None)
    check("France: 9 digits after +33, the 0 is not needed (user, 2026-10-14) → 0612345678",
          ok("612345678") == ok("6 12 34 56 78") == "0612345678")
    check("France: too short or too long refused", ok("061234567") is None and ok("06123456789") is None
          and ok("61234567") is None and ok("6123456789") is None)
    check("« 0000000051 » (00 is not a French number) refused", ok("0000000051") is None)
    check("an unknown country code refused", ok("+999 12345678") is None)
    check("the key compares the same person written two ways",
          CF.phone_digits("+33 6 12 34 56 78") == CF.phone_digits("06.12.34.56.78") == "0612345678")
    js = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "lib", "phone.js"), encoding="utf-8").read()
    js_codes = set(re.findall(r"\['[A-Z]{2}', (?:'[^']*'|\"[^\"]*\"), '(\d+)'\]", js))
    check(f"the server's country codes are the forms' list ({len(js_codes)} codes)", js_codes == set(DIAL_CODES))

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})

    def join(phone, email="", postal="37000", name="Client"):
        return http("POST", "/api/join/cafe", json={"name": name, "phone": phone, "email": email, "postal_code": postal,
                                                    "birthday": "1990-01-02", "consent": True})

    print("\n2. Inscription client")
    r = join("06 11 11 11 11", "lea@exemple.fr", name="Léa")
    c = db.customers.find_one({"barcode_id": r.json().get("barcode_id")})
    check(f"a new customer is created, phone stored as 0611111111 ({r.status_code})",
          r.status_code == 200 and c and c["phone"] == "0611111111")
    r = join("06#11111111")
    check(f"« # » refused in French ({r.status_code})", r.status_code == 400 and "chiffres" in str(r.json()))
    r = join("0622222222", postal="Tours")
    check(f"text in the postal code refused ({r.status_code})", r.status_code == 400 and "Code postal" in str(r.json()))
    r = join("+33 6 11 11 11 11", name="Quelqu'un")
    det = r.json().get("detail") or {}
    check(f"Léa's number (written « +33 ») by someone else: 409 already_member ({r.status_code})",
          r.status_code == 409 and det.get("code") == "already_member" and "Le Café" in det.get("message", ""))
    check("…and NO card, NO owner key in the answer", "barcode_id" not in r.json() and "card_key" not in r.json())
    r = join("0633333333", "LEA@exemple.fr")
    det = r.json().get("detail") or {}
    check(f"Léa's e-mail with another number: 409 email_taken (QA F16) ({r.status_code})",
          r.status_code == 409 and det.get("code") == "email_taken")
    check("…no second customer", db.customers.count_documents({"tenant_id": "t1"}) == 1)
    db.customers.update_one({"id": c["id"]}, {"$set": {"deleted_at": "2026-10-09"}})
    r = join("0611111111", "lea@exemple.fr", name="Léa")
    check(f"an erased customer no longer counts: Léa can sign up again ({r.status_code})", r.status_code == 200)
    r = join("+44 7700 900123", name="Tom")
    check(f"a UK number signs up ({r.status_code})", r.status_code == 200
          and db.customers.find_one({"barcode_id": r.json()["barcode_id"]})["phone"] == "+447700900123")

    print("\n3. API, fiche, inscription commerce")
    import features.merchant_api as MA
    created = MA.create_customer(MA.CustomerIn(name="Léa", phone="0611111111", consent=True),
                                 c=type("C", (), {"tenant_id": "t1"})())
    check("the merchant API (signed in as the shop) still gets the existing card back", created["created"] is False)
    try:
        MA.create_customer(MA.CustomerIn(name="X", phone="0612#45678", consent=True), c=type("C", (), {"tenant_id": "t1"})())
        api_refused = False
    except HTTPException as e:
        api_refused = e.status_code == 400
    check("the merchant API refuses « # » too", api_refused)
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    lea = db.customers.find_one({"tenant_id": "t1", "phone": "0611111111", "deleted_at": {"$exists": False}})
    r = http("PUT", f"/api/owner/clients/{lea['id']}/fiche", headers=H, json={"phone": "0612*45678"})
    check(f"« Modifier la fiche » refuses « * » ({r.status_code})", r.status_code == 400)
    r = http("PUT", f"/api/owner/clients/{lea['id']}/fiche", headers=H, json={"phone": "+33 6 44 44 44 44"})
    check(f"…and stores « +33 6 44… » as 0644444444 ({r.status_code})",
          r.status_code == 200 and db.customers.find_one({"id": lea["id"]})["phone"] == "0644444444")
    base = {"first_name": "Nora", "last_name": "Ben", "email": "nora@gmail.com", "password": "Cafe-Lumiere2026!",
            "accepted_terms": True, "role": "business_owner"}
    import services.email_check as EC
    EC.check = lambda e: {"ok": True}
    r = http("POST", "/api/auth/register", json={**base, "phone": "06*12345678"})
    check(f"business signup refuses « * » ({r.status_code})", r.status_code == 400 and "chiffres" in str(r.json()))
    r = http("POST", "/api/auth/register", json={**base, "phone": "+33 6 55 55 55 55"})
    check(f"…and accepts a valid one ({r.status_code})", r.status_code == 200)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
