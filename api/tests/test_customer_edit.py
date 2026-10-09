"""
Clients › « Modifier la fiche » / « Ajuster points / tampons » (QA UX04, user 2026-10-08).

Run: cd api && /usr/local/bin/python3 tests/test_customer_edit.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-customer-edit")
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
    from features import wallet_passes as W
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
                           "branches": [{"id": "b1", "name": "Centre"}, {"id": "b2", "name": "Nord"}]})
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
        {"email": "m@x.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["b2"], "scope": "partial"},
        {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
    ])
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Léa Martin", "phone": "06 11 11 11 11", "email": "lea@x.fr",
         "birthday": "03-14", "postal_code": "37000", "barcode_id": "FT-0000000A", "points": 50, "visits": 12,
         "visits_at_last_redemption": 10, "total_amount_paid": 120.0, "tier": "silver", "branch_id": "b1", "created_at": now},
        {"id": "c2", "tenant_id": "t1", "name": "Paul", "phone": "06 22 22 22 22", "email": "paul@x.fr",
         "barcode_id": "FT-0000000B", "points": 0, "visits": 1, "branch_id": "b1", "created_at": now},
    ])
    tok = lambda e, r: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": "t1"})}   # noqa: E731
    O, M, ST = tok("o@x.fr", "business_owner"), tok("m@x.fr", "manager"), tok("s@x.fr", "staff")

    def call(method, url, h=O, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=h, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    woken = []
    W.notify_passes = lambda serials, **k: woken.extend(serials) or {}

    print("\nModifier la fiche")
    f = call("GET", "/api/owner/clients/c1/fiche").json()
    check("the form gets the client and the sources", f["client"]["name"] == "Léa Martin" and f["sources"])
    r = call("PUT", "/api/owner/clients/c1/fiche", json={"name": "Léa Dupont", "phone": "07 33 33 33 33", "birthday": "25/12",
                                                         "postal_code": "37100", "is_student": True, "acquisition_source": "insta"})
    c = db.customers.find_one({"id": "c1"})
    check(f"saved ({r.status_code}): name, phone (stored as 0733333333), birthday read « 25/12 » as 12-25, postal, student, source",
          r.status_code == 200 and c["name"] == "Léa Dupont" and c["phone"] == "0733333333" and c["birthday"] == "12-25"
          and c["postal_code"] == "37100" and c["is_student"] is True and c["acquisition_source"] == "instagram")
    check("the name is on the Wallet card: it is refreshed", "FT-0000000A" in woken)
    for field, bad in (("phone", "abc"), ("postal_code", "ABCDE"), ("birthday", "13-99"), ("email", "x@"), ("name", " ")):
        check(f"{field} « {bad} » refused", call("PUT", "/api/owner/clients/c1/fiche", json={field: bad}).status_code == 400)
    r = call("PUT", "/api/owner/clients/c1/fiche", json={"phone": "06.22.22.22.22"})
    check(f"another client's phone is refused, naming them ({r.json().get('detail')})", r.status_code == 409 and "Paul" in r.json()["detail"])
    check("another client's e-mail too", call("PUT", "/api/owner/clients/c1/fiche", json={"email": "PAUL@x.fr"}).status_code == 409)
    check("the e-mail can be emptied", call("PUT", "/api/owner/clients/c1/fiche", json={"email": ""}).status_code == 200
          and db.customers.find_one({"id": "c1"})["email"] == "")
    check("nothing changed: nothing written", call("PUT", "/api/owner/clients/c1/fiche", json={"name": "Léa Dupont"}).json()["changed"] == [])

    print("\nAjuster points / tampons")
    check("a reason is compulsory", call("POST", "/api/owner/clients/c1/ajustement", json={"points": 10}).status_code == 400)
    check("nothing to adjust is refused", call("POST", "/api/owner/clients/c1/ajustement", json={"reason": "x"}).status_code == 400)
    woken.clear()
    r = call("POST", "/api/owner/clients/c1/ajustement", json={"points": 25, "visits": 3, "reason": "Visites oubliées au comptoir"})
    c = db.customers.find_one({"id": "c1"})
    check(f"+25 points and +3 stamps ({r.json().get('text')})", r.status_code == 200 and c["points"] == 75 and c["visits"] == 15
          and r.json()["client"]["stamps_in_cycle"] == 5)
    check("no visit is invented: the shop's figures stay the scans'", db.visits.count_documents({}) == 0)
    check("the Wallet card refreshes", "FT-0000000A" in woken)
    check("points never go below 0", call("POST", "/api/owner/clients/c1/ajustement", json={"points": -500, "reason": "x"}).status_code == 400)
    r = call("POST", "/api/owner/clients/c1/ajustement", json={"visits": -6, "reason": "Erreur"})
    check(f"stamps never go below the current card ({r.json().get('detail')})", r.status_code == 400 and "5 tampon" in r.json()["detail"])
    call("POST", "/api/owner/clients/c1/ajustement", json={"visits": 6, "reason": "Rattrapage"})
    check("the tier follows the visits (21 → gold)", db.customers.find_one({"id": "c1"})["tier"] == "gold")

    print("\nQui peut")
    check("staff cannot", call("PUT", "/api/owner/clients/c2/fiche", ST, json={"name": "X"}).status_code == 403)
    check("a manager of another establishment cannot", call("PUT", "/api/owner/clients/c2/fiche", M, json={"name": "X"}).status_code in (403, 404))
    check("an unknown client is 404", call("GET", "/api/owner/clients/zz/fiche").status_code == 404)

    print("\nHistorique")
    f = call("GET", "/api/owner/clients/c1/fiche").json()
    kinds = [x["kind"] for x in f["changes"]]
    check("the client's changes are listed, newest first", kinds[:3] == ["adjust", "adjust", "profile"] and f["changes"][0]["reason"] == "Rattrapage")
    h = call("GET", "/api/owner/history/activity").json()
    rows = h.get("rows") or h.get("items") or []
    acts = {r.get("action") for r in rows}
    check(f"the Historique shows « Fiche client modifiée » and « Ajustement manuel » ({acts})", {"client_update", "adjustment"} <= acts)
    adj = next(r for r in rows if r.get("action") == "adjustment")
    check("with the reason and who did it", "Rattrapage" in adj.get("detail", "") and "o@x.fr" in adj.get("detail", ""))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
