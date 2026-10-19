"""
QA R7 F40 (2026-10-18): a Lyon branch card's « À propos » showed the main
establishment's address, in another city. A client's card — web « À propos »
and the Wallet pass's back — now gives their own establishment's address and
phone, as saved in Paramètres › Établissement.

Run: cd api && /usr/local/bin/python3 tests/test_store_address.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-store-address")
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
    import features.wallet_passes as WP

    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "ok", "name": "OK", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "address": "Chemin de la Luona, 06480 La Colle-sur-Loup",
                           "phone": "0400000000",
                           "branches": [{"id": "main", "name": "OK", "is_main": True},
                                        {"id": "lyon", "name": "QA Branch B Lyon", "street": "20 rue du Test",
                                         "postal_code": "69001", "city": "Lyon", "phone": "0478000000"},
                                        {"id": "bare", "name": "Sans adresse"}]})
    # a card copied from the main one keeps its typed address
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "OK",
                                  "details": {"address": "Chemin de la Luona, 06480 La Colle-sur-Loup", "about": "Bienvenue"}})
    for cid, br in (("c_main", "main"), ("c_lyon", "lyon"), ("c_bare", "bare")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": "QA", "barcode_id": f"FT-{cid.upper()}",
                                 "branch_id": br, "visits": 0, "points": 0})

    def payload(cid):
        return server._serialize_card_payload(db.customers.find_one({"id": cid}, {"_id": 0}))

    def back(p):
        sc = WP.build_pass_json(p)
        sc = sc.get("storeCard") or sc.get("generic") or {}
        return {f["key"]: f["value"] for f in sc.get("backFields", [])}

    p = payload("c_lyon")
    check(f"Lyon card « À propos »: the Lyon address ({p['card']['details'].get('address')})",
          p["card"]["details"].get("address") == "20 rue du Test, 69001 Lyon")
    check("…and the Lyon phone", p["card"]["details"].get("phone") == "0478000000")
    check("…the rest of « À propos » kept", p["card"]["details"].get("about") == "Bienvenue")
    b = back(p)
    check(f"Lyon pass back: Lyon address ({b.get('address')})", b.get("address") == "20 rue du Test, 69001 Lyon")
    check("Lyon pass back: Lyon phone", b.get("phone") == "0478000000")

    p = payload("c_main")
    check("main store card unchanged", p["card"]["details"].get("address") == "Chemin de la Luona, 06480 La Colle-sur-Loup"
          and back(p).get("address") == "Chemin de la Luona, 06480 La Colle-sur-Loup")
    p = payload("c_bare")
    check("an establishment with no address saved keeps the card's",
          p["card"]["details"].get("address") == "Chemin de la Luona, 06480 La Colle-sur-Loup")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
