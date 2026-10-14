"""
One card per establishment (user, 2026-10-14): I hold Royal Trim Liberté's
card, my friend holds Palissy's. Scanning my friend's card must open
Palissy's signup — not my Liberté card — and signing up there makes me a new
client of Palissy, not « already a client » of the account.

Run: cd api && /usr/local/bin/python3 tests/test_per_store_signup.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-per-store-signup")
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
    from services import card_owner as CO

    db = server.db

    def http(method, url, **kw):
        import httpx

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM LIBÉRTÉ", "plan": "vip", "subscription_status": "active",
         "is_active": True, "branches": [{"id": "main", "name": "ROYAL TRIM LIBÉRTÉ", "is_main": True},
                                         {"id": "pal", "name": "ROYAL TRIM PALISSY"}]},
        {"id": "t2", "slug": "solo", "name": "Solo Café", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_many([{"tenant_id": "t1", "card_name": "ROYAL TRIM"}, {"tenant_id": "t2", "card_name": "Solo"}])
    stores = {s["id"]: s["slug"] for s in http("GET", "/api/join/royal-trim/page").json()["stores"]}
    me_phone, me_mail = "06 11 22 33 44", "moi@gmail.com"
    db.customers.insert_many([
        # me: Liberté (the main store), once without a store as the old cards are
        {"id": "me", "tenant_id": "t1", "name": "Moi", "barcode_id": "FT-ME000001", "phone": me_phone,
         "email": me_mail, "visits": 0, "points": 0},
        {"id": "friend", "tenant_id": "t1", "name": "Ami", "barcode_id": "FT-FR000001", "phone": "06 99 88 77 66",
         "branch_id": "pal", "visits": 0, "points": 0},
        {"id": "lib2", "tenant_id": "t1", "name": "Autre", "barcode_id": "FT-LB000001", "phone": "06 55 44 33 22",
         "branch_id": "main", "visits": 0, "points": 0},
    ])
    mine = {"FT-ME000001": CO.key_for("FT-ME000001")}

    print("1. Scanning a card on my phone")
    w = CO.whose(db, "FT-FR000001", None, mine)
    check(f"my friend's Palissy card → Palissy's signup, not my Liberté card ({w})",
          w["view"] == "join" and w["slug"] == "royal-trim" and w.get("store") == stores["pal"] and w["parrain"] == "FT-FR000001")
    w = CO.whose(db, "FT-LB000001", None, mine)
    check(f"another Liberté client's card → my own Liberté card ({w})", w["view"] == "own" and w["barcode_id"] == "FT-ME000001")
    w = CO.whose(db, "FT-FR000001", None, {})
    check("no card on the phone → Palissy's signup", w["view"] == "join" and w.get("store") == stores["pal"])

    print("\n2. Signing up at Palissy with my Liberté phone and e-mail")
    base = {"name": "Moi", "phone": me_phone, "email": me_mail, "postal_code": "37000", "birthday": "25/12/1990",
            "consent": True}
    r = http("POST", "/api/join/royal-trim", json={**base, "store": stores["pal"], "parrain_barcode": "FT-FR000001"})
    check(f"a new Palissy client ({r.status_code} {str(r.json())[:120]})", r.status_code == 200 and r.json().get("barcode_id"))
    new = db.customers.find_one({"barcode_id": (r.json() or {}).get("barcode_id")}) or {}
    check("…his own card, at Palissy", new.get("branch_id") == "pal" and new.get("id") != "me")
    r = http("POST", "/api/join/royal-trim", json={**base, "store": stores["pal"]})
    check(f"twice at Palissy: already a client there ({r.status_code})", r.status_code == 409
          and "PALISSY" in str(r.json()))
    r = http("POST", "/api/join/royal-trim", json={**base, "store": stores["main"]})
    check(f"at Liberté (my card has no store): already a client ({r.status_code})", r.status_code == 409)

    print("\n3. A one-shop account: as before")
    db.customers.insert_one({"id": "s1", "tenant_id": "t2", "name": "A", "barcode_id": "FT-SO000001",
                             "phone": "06 12 12 12 12", "visits": 0, "points": 0})
    r = http("POST", "/api/join/solo", json={**base, "phone": "06 12 12 12 12", "email": ""})
    check(f"same phone → already a client ({r.status_code})", r.status_code == 409)
    w = CO.whose(db, "FT-SO000001", None, {})
    check("scan → its signup, no store", w["view"] == "join" and "store" not in w)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
