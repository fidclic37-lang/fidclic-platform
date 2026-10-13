"""
A customer's details are real (user, 2026-10-11): nobody older than 85, a
real e-mail (not « kuch bhi »), a French postal code from La Poste's list —
on the signup form, in « Modifier la fiche » and in an import. Phone and
e-mail stay one customer each.

Run: cd api && /usr/local/bin/python3 tests/test_signup_validation.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-signup-validation")
os.environ.setdefault("DISABLE_SEED", "1")

import services.email_check as EC  # noqa: E402

DNS = {}                                   # domain → True / False; anything else: unreachable
EC.domain_receives_mail = lambda d: DNS.get(d)
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
    from features import client_import as CI

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def refused(fn, *a, **k):
        try:
            fn(*a, **k)
            return None
        except HTTPException as e:
            return e.detail

    today = CF._paris_today()

    def born(years_ago, days=0):
        d = dt.date(today.year - years_ago, today.month, min(today.day, 28)) + dt.timedelta(days=days)
        return d.strftime("%d/%m/%Y")

    print("\nAge: 85 at most")
    check("85 today: welcome", CF.birth(born(85), need_year=True)["birth_date"])
    msg = refused(CF.birth, born(86), need_year=True)
    check(f"86: refused ({msg})", msg and "85 ans" in msg)
    check("85 and 364 days: still 85", not refused(CF.birth, born(86, days=1), need_year=True))
    check("a date already on file is still read (max_age off)", CF.birth(born(90), max_age=False)["birth_date"])
    check("day and month only (no year): no age to judge", CF.birth("25/12")["birthday"] == "12-25")

    print("\nPostal code: La Poste's list")
    for good in ("37000", "75001", "20000", "97400", "98000"):
        check(f"{good} accepted", CF.postal_code(good) == good)
    for bad in ("99999", "00000", "37999", "75000"):
        msg = refused(CF.postal_code, bad)
        check(f"{bad} refused ({msg})", msg and "inconnu en France" in msg)
    check("not five digits: the old message", "5 chiffres" in (refused(CF.postal_code, "3700A") or ""))

    print("\nE-mail: a real address")
    DNS.update({"boulangerie-paul.fr": True, "nexistepas-zz.fr": False})
    check("empty stays empty (optional)", CF.email("") == "")
    check("a normal address", CF.email("marie@gmail.com") == "marie@gmail.com")
    check("a shop's own domain that receives mail", CF.email("contact@boulangerie-paul.fr"))
    for bad, why in (("marie@gmial.com", "Vouliez-vous dire marie@gmail.com"), ("x@yopmail.com", "jetables"),
                     ("marie@", "invalide"), ("marie dupont@gmail.com", "invalide"), ("a@b.c", "invalide"),
                     ("marie@nexistepas-zz.fr", "ne reçoit pas")):
        msg = refused(CF.email, bad)
        check(f"« {bad} » refused ({msg})", msg and why in msg)
    check("DNS unreachable: accepted (a resolver hiccup never stops a signup)", CF.email("lea@inconnu-dns.fr"))

    print("\nThe signup page: each refusal under its field")
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "sector": "cafe"})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "Café", "reward_threshold_stamps": 10})
    base = {"name": "Léa Martin", "phone": "06 11 22 33 44", "postal_code": "37000", "birthday": born(30),
            "email": "lea@gmail.com", "consent": True}
    for field, value, key in (("postal_code", "99999", "postal_code"), ("birthday", born(90), "birth"),
                              ("email", "lea@gmial.com", "email"), ("email", "lea@yopmail.com", "email")):
        r = http("POST", "/api/join/cafe", json={**base, field: value})
        d = r.json().get("detail") or {}
        check(f"{field} « {value} »: 400 under « {key} » ({d.get('message') if isinstance(d, dict) else d})",
              r.status_code == 400 and isinstance(d, dict) and d.get("code") == "invalid_field" and d.get("field") == key)
    r = http("POST", "/api/join/cafe", json=base)
    check(f"everything right: the card ({r.status_code})", r.status_code == 200 and r.json().get("barcode_id"))
    r = http("POST", "/api/join/cafe", json={**base, "email": "autre@gmail.com"})
    check("the same phone again: refused (one card per person)", r.status_code == 409)
    r = http("POST", "/api/join/cafe", json={**base, "phone": "07 99 88 77 66"})
    check("the same e-mail with another phone: refused", r.status_code == 409 and r.json()["detail"]["code"] == "email_taken")

    print("\nThe merchant API (signed in as the shop): the same rules, a plain message")
    try:
        server.join_program("cafe", server.JoinRequest(name="Paul", phone="0655443322", postal_code="99999", birthday=""))
        check("refused", False)
    except HTTPException as e:
        check(f"unknown postal code refused ({e.detail})", isinstance(e.detail, str) and "inconnu" in e.detail)

    print("\n« Modifier la fiche »: the rules judge what the owner changes")
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    OWNER = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.customers.insert_one({"id": "old", "tenant_id": "t1", "barcode_id": "FT-OLD00001", "name": "Jean Ancien",
                             "phone": "0612121212", "email": "jean@vieux-domaine.fr", "postal_code": "99999",
                             "birthday": "03-04", "birth_date": f"{today.year - 90}-03-04", "visits": 4})
    fiche = http("GET", "/api/owner/clients/old/fiche", headers=OWNER).json()["client"]
    r = http("PUT", "/api/owner/clients/old/fiche", headers=OWNER, json={
        "name": "Jean Ancien-Martin", "phone": fiche["phone"], "email": fiche["email"], "postal_code": fiche["postal_code"],
        "birthday": f"04/03/{today.year - 90}"})
    check(f"a client on file before the rules: still editable ({r.status_code})", r.status_code == 200
          and db.customers.find_one({"id": "old"})["name"] == "Jean Ancien-Martin")
    r = http("PUT", "/api/owner/clients/old/fiche", headers=OWNER, json={"postal_code": "37999"})
    check(f"a new postal code: must be French ({r.status_code})", r.status_code == 400 and "inconnu" in r.json()["detail"])
    r = http("PUT", "/api/owner/clients/old/fiche", headers=OWNER, json={"birthday": born(95)})
    check(f"a new date of birth: 85 at most ({r.status_code})", r.status_code == 400 and "85 ans" in r.json()["detail"])
    r = http("PUT", "/api/owner/clients/old/fiche", headers=OWNER, json={"email": "jean@hotmial.fr"})
    check(f"a new e-mail: a real one ({r.json().get('detail')})", r.status_code == 400 and "hotmail.fr" in r.json()["detail"])
    r = http("PUT", "/api/owner/clients/old/fiche", headers=OWNER, json={"email": "lea@gmail.com"})
    check("another client's e-mail: refused", r.status_code == 409)
    r = http("PUT", "/api/owner/clients/old/fiche", headers=OWNER, json={"postal_code": "37100", "birthday": born(40)})
    check("corrected: saved", r.status_code == 200 and db.customers.find_one({"id": "old"})["postal_code"] == "37100")

    print("\nAn import: the same rules, line by line")
    rows = CI.classify("t1", [
        {"name": "Ok", "email": "ok@gmail.com", "phone": "0601010101", "birthday": None, "postal_code": "37000", "city": ""},
        {"name": "Typo", "email": "t@gmial.com", "phone": "", "birthday": None, "postal_code": "", "city": ""},
        {"name": "Jetable", "email": "j@yopmail.com", "phone": "", "birthday": None, "postal_code": "", "city": ""},
        {"name": "Cp", "email": "", "phone": "0602020202", "birthday": None, "postal_code": "99999", "city": ""},
        {"name": "Déjà", "email": "LEA@gmail.com".lower(), "phone": "", "birthday": None, "postal_code": "", "city": ""},
    ])
    st = {r["name"]: (r["status"], r["reason"]) for r in rows}
    check(f"a good line: new ({st['Ok']})", st["Ok"][0] == "new")
    check(f"a typo: refused with the fix ({st['Typo'][1]})", st["Typo"][0] == "invalid" and "gmail.com" in st["Typo"][1])
    check("a throwaway inbox: refused", st["Jetable"][0] == "invalid")
    check(f"a postal code not in France: refused ({st['Cp'][1]})", st["Cp"][0] == "invalid" and "inconnu" in st["Cp"][1])
    check("an e-mail already a client's: not a new card", st["Déjà"][0] == "existing")


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
