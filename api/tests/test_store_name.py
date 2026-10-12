"""
Renaming one establishment (user, 2026-10-12: « ek ka naam change kiye toh
baaki 2 k bhi change ho, aisa nahi »): Paramètres › Établissement shows and
edits the establishment chosen in the menu — its name, address and phone —
and its name is what its clients see (card, pass, Google, signup page).

Run: cd api && /usr/local/bin/python3 tests/test_store_name.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-store-name")
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
    import features.wallet_passes as WP
    from features import store_cards as SC

    db = server.db
    pushed = []
    WP.notify_passes = lambda serials, *a, **k: pushed.append(sorted(s for s in serials if s)) or {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM LIBÉRTÉ", "plan": "vip", "subscription_status": "active",
         "is_active": True, "street": "11 Place de la Liberté", "postal_code": "37000", "city": "Tours", "phone": "0247000000",
         "branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True, "street": "11 Place de la Liberté",
                       "postal_code": "37000", "city": "Tours"},
                      {"id": "pal", "name": "ROYAL TRIM PALISSY", "street": "2 rue Palissy", "postal_code": "37000",
                       "city": "Tours", "phone": "0247111111"},
                      {"id": "mon", "name": "ROYAL TRIM PL-MONSTER", "street": "5 place Monstre", "postal_code": "37100",
                       "city": "Tours"}]},
        {"id": "t2", "slug": "solo", "name": "Solo Café", "plan": "vip", "subscription_status": "active", "is_active": True,
         "street": "1 rue Solo", "postal_code": "37000", "city": "Tours"},
    ])
    db.card_templates.insert_many([{"tenant_id": "t1", "card_name": "ROYAL TRIM"}, {"tenant_id": "t2", "card_name": "Solo"}])
    db.customers.insert_one({"id": "c_pal", "tenant_id": "t1", "name": "Léa", "barcode_id": "FT-PAL00001",
                             "branch_id": "pal", "visits": 0, "points": 0, "deleted_at": None})
    db.customers.insert_one({"id": "c_mon", "tenant_id": "t1", "name": "Marc", "barcode_id": "FT-MON00001",
                             "branch_id": "mon", "visits": 0, "points": 0, "deleted_at": None})
    for e, role, t in (("o@x.fr", "business_owner", "t1"), ("a@x.fr", "administrateur", "t1"), ("r@x.fr", "business_owner", "t2")):
        db.users.insert_one({"email": e, "role": role, "tenant_id": t, "active": True,
                             **({"branch_ids": ["pal"]} if role == "administrateur" else {})})
    tok = lambda e, r, t="t1": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})  # noqa: E731
    OWNER, ADMIN, SOLO = tok("o@x.fr", "business_owner"), tok("a@x.fr", "administrateur"), tok("r@x.fr", "business_owner", "t2")

    def as_(store, who=OWNER):
        return {"Authorization": who, **({"X-FidClic-Store": store} if store else {})}

    def branch(sid):
        return next(b for b in db.tenants.find_one({"id": "t1"})["branches"] if b["id"] == sid)

    print("1. The page is the chosen establishment's")
    v = http("GET", "/api/owner/etablissement", headers=as_("pal")).json()
    check(f"PALISSY chosen: its name ({v['business']['name']})", v["business"]["name"] == "ROYAL TRIM PALISSY")
    check("…its address and phone", v["address"]["street"] == "2 rue Palissy" and v["business"]["phone"] == "0247111111")
    check("…the page knows it is one establishment", (v.get("store") or {}).get("id") == "pal")
    v = http("GET", "/api/owner/etablissement", headers=as_("mon")).json()
    check("PL-MONSTER chosen: its own", v["business"]["name"] == "ROYAL TRIM PL-MONSTER" and v["address"]["postal_code"] == "37100")
    check("…no phone of its own: the account's", v["business"]["phone"] == "0247000000")

    print("\n2. Renaming PALISSY renames PALISSY only")
    pushed.clear()
    r = http("PUT", "/api/owner/etablissement", headers=as_("pal"),
             json={"business": {"name": "ROYAL TRIM PALISSY CENTRE", "phone": "0247222222"},
                   "address": {"street": "3 rue Palissy", "postal_code": "37000", "city": "Tours"}})
    check(f"saved ({r.status_code})", r.status_code == 200 and r.json()["business"]["name"] == "ROYAL TRIM PALISSY CENTRE")
    check("PALISSY's name, phone and address changed", branch("pal")["name"] == "ROYAL TRIM PALISSY CENTRE"
          and branch("pal")["phone"] == "0247222222" and branch("pal")["street"] == "3 rue Palissy")
    check("the other two keep theirs", branch("mon")["name"] == "ROYAL TRIM PL-MONSTER" and branch("main")["name"] == "ROYAL TRIM")
    t = db.tenants.find_one({"id": "t1"})
    check("the account's name, phone and address are untouched", t["name"] == "ROYAL TRIM LIBÉRTÉ"
          and t["phone"] == "0247000000" and t["street"] == "11 Place de la Liberté")
    br = http("GET", "/api/owner/branches", headers=as_("pal")).json()
    names = sorted(b["name"] for b in (br.get("branches") if isinstance(br, dict) else br))
    check(f"the menu lists the new name, once ({names})",
          names == ["ROYAL TRIM", "ROYAL TRIM PALISSY CENTRE", "ROYAL TRIM PL-MONSTER"])
    check(f"PALISSY's clients' cards are refreshed, only theirs ({pushed})", pushed == [["FT-PAL00001"]])

    r = http("PUT", "/api/owner/etablissement", headers=as_("main"),
             json={"address": {"street": "12 Place de la Liberté", "postal_code": "37000", "city": "Tours"}})
    check("the main store's address: the account's follows (as before)", r.status_code == 200
          and branch("main")["street"] == "12 Place de la Liberté"
          and db.tenants.find_one({"id": "t1"})["street"] == "12 Place de la Liberté")
    check("…PALISSY's stays", branch("pal")["street"] == "3 rue Palissy")
    check("an empty name is refused", http("PUT", "/api/owner/etablissement", headers=as_("pal"),
                                           json={"business": {"name": "  "}}).status_code == 400)
    check("an administrateur cannot rename", http("PUT", "/api/owner/etablissement", headers=as_("pal", ADMIN),
                                                  json={"business": {"name": "X"}}).status_code == 403)

    print("\n3. Its clients see its name")
    pal = server._serialize_card_payload(db.customers.find_one({"id": "c_pal"}, {"_id": 0}))
    mon = server._serialize_card_payload(db.customers.find_one({"id": "c_mon"}, {"_id": 0}))
    check(f"PALISSY's client: « ROYAL TRIM PALISSY CENTRE » ({pal['tenant']['name']})",
          pal["tenant"]["name"] == "ROYAL TRIM PALISSY CENTRE")
    check("PL-MONSTER's client: its own name", mon["tenant"]["name"] == "ROYAL TRIM PL-MONSTER")
    pj = WP.build_pass_json(pal)
    check(f"Apple pass: organizationName ({pj.get('organizationName')})", pj.get("organizationName") == "ROYAL TRIM PALISSY CENTRE")
    WP._gw_issuer = lambda: "333"
    with SC.store("t1", "pal"):
        url = WP._gw_image_url("t1", "name", {"logo_url": "x", "_shop_name": "ROYAL TRIM PALISSY CENTRE"})
    check("Google: the name image is PALISSY's", url.endswith("&store=pal"))
    s = http("GET", "/api/owner/card/settings", headers=as_("pal")).json()
    check("the card page says PALISSY's name", s["tenant"]["name"] == "ROYAL TRIM PALISSY CENTRE")
    pub = http("GET", "/api/join/royal-trim/page").json()
    check("the signup page lists the new name", any(x["name"] == "ROYAL TRIM PALISSY CENTRE" for x in pub["stores"]))

    print("\n4. A one-shop account: as before")
    v = http("GET", "/api/owner/etablissement", headers=as_("pal", SOLO)).json()
    check("its own name, no establishment", v["business"]["name"] == "Solo Café" and v.get("store") is None)
    r = http("PUT", "/api/owner/etablissement", headers=as_(None, SOLO), json={"business": {"name": "Solo Café Tours"}})
    check("renamed: the account's name", r.status_code == 200 and db.tenants.find_one({"id": "t2"})["name"] == "Solo Café Tours")

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
