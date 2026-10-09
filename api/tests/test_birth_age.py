"""
The full date of birth and the age (user, 2026-10-09): the signup asks
JJ/MM/AAAA, the server keeps the day (birthday automations) and the date, and
the owner sees the age in Clients — on the shop's (Paris) calendar.

Run: cd api && /usr/local/bin/python3 tests/test_birth_age.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-birth-age")
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
    from services import customer_fields as CF

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    print("1. L'âge, au jour près")
    D = dt.date
    check("36 on his birthday, 35 the day before",
          CF.age_of("1990-10-09", D(2026, 10, 9)) == 36 and CF.age_of("1990-10-10", D(2026, 10, 9)) == 35)
    check("born 29 February: one year older on 1 March of a common year",
          CF.age_of("2000-02-29", D(2026, 2, 28)) == 25 and CF.age_of("2000-02-29", D(2026, 3, 1)) == 26)
    check("no year, no age", CF.age_of(None) is None and CF.age_of("") is None)

    print("\n2. L'inscription demande la date complète")
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})

    def join(bday, tel):
        return http("POST", "/api/join/cafe", json={"name": "Inès Martin", "phone": tel, "postal_code": "37000",
                                                    "birthday": bday, "consent": True})
    r = join("25/12/1990", "0611111111")
    c = db.customers.find_one({"barcode_id": r.json().get("barcode_id")}) or {}
    check(f"« 25/12/1990 » → birthday 12-25 and birth_date 1990-12-25 ({r.status_code})",
          r.status_code == 200 and c.get("birthday") == "12-25" and c.get("birth_date") == "1990-12-25")
    for bad, why in (("25/12", "complète"), ("31/04/1990", "n'existe pas"), ("01/01/2099", "année"), ("12/1990", "JJ/MM/AAAA")):
        r = join(bad, "0622222222")
        check(f"« {bad} » refused: {why}", r.status_code == 400 and why in str(r.json()))

    print("\n3. Le propriétaire voit l'âge")
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    rows = http("GET", "/api/owner/clients/list", headers=H).json()["rows"]
    want = CF.age_of("1990-12-25")
    check(f"Clients shows Inès's age ({rows[0].get('age')})", rows[0].get("age") == want)
    csv = http("GET", "/api/owner/clients/export", headers=H).text.splitlines()
    check("the export has an « Âge » column", csv[0].endswith("Âge") and csv[1].endswith(str(want)))
    cid = rows[0]["id"]
    r = http("PUT", f"/api/owner/clients/{cid}/fiche", headers=H, json={"birthday": "2001-03-04"})
    f = http("GET", f"/api/owner/clients/{cid}/fiche", headers=H).json()["client"]
    check(f"« Modifier la fiche » sets the full date ({r.status_code})",
          f["birth_date"] == "2001-03-04" and f["birthday"] == "03-04" and f["age"] == CF.age_of("2001-03-04"))

    print("\n4. L'API caisse peut toujours envoyer jour et mois seulement")
    import features.merchant_api as MA
    out = MA.create_customer(MA.CustomerIn(name="Tom", phone="0633333333", birthday="05-06", consent=True),
                             c=type("C", (), {"tenant_id": "t1"})())
    t = db.customers.find_one({"id": out["id"]})
    check("day and month kept, no age", t["birthday"] == "05-06" and not t.get("birth_date"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
