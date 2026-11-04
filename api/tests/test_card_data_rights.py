"""
Exporting or erasing a customer's data from a shop login follows the rule of
Paramètres › Données & confidentialité: the owner only. The customer's own
phone always can. A disabled account or a suspended shop has no access to card
routes, and a look-only account changes nothing. The audit log names who did it.

« Voir sa carte » stays open to any active login of the shop.

Run: cd api && python3 tests/test_card_data_rights.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-data-rights")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


def main():
    import auth
    import server
    import httpx
    from services import card_owner as CO

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True, "plan": "vip",
                           "subscription_status": "active",
                           "branches": [{"id": "a1", "name": "Un"}, {"id": "a2", "name": "Deux"}]})
    db.tenants.insert_one({"id": "t2", "slug": "autre", "name": "Autre", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})

    n = {"i": 0}

    def card(branch="a2"):
        """A fresh customer each time: erasing one is irreversible."""
        n["i"] += 1
        bc = f"FT-RIGHTS{n['i']:02d}"
        db.customers.insert_one({"id": f"c{n['i']}", "tenant_id": "t1", "barcode_id": bc, "name": "Marie Dupont",
                                 "email": "marie@exemple.fr", "phone": "0611111111", "visits": 3, "points": 10,
                                 "branch_id": branch, "home_branch_id": branch})
        db.visits.insert_one({"customer_id": f"c{n['i']}", "tenant_id": "t1", "branch_id": branch})
        return bc

    def login(role, tenant="t1", claims=None, **user):
        email = f"{role}-{tenant}-{len(user)}-{len(claims or {})}@x.fr"
        db.users.update_one({"email": email}, {"$set": {"email": email, "role": role, "tenant_id": tenant, **user}},
                            upsert=True)
        data = {"sub": email, "role": role, "tenant_id": tenant, **(claims or {})}
        return {"Authorization": "Bearer " + auth.create_access_token(data)}

    def erased(bc):
        return db.customers.find_one({"barcode_id": bc}).get("gdpr_erased_at") is not None \
            or db.customers.find_one({"barcode_id": bc}).get("name") != "Marie Dupont"

    def forget(bc, headers):
        return http("POST", f"/api/card/{bc}/forget-me", headers=headers, json={"confirm": True})

    owner = login("business_owner")
    admin = login("super_admin", tenant=None)
    staff = login("staff", branch_ids=["a1", "a2"])
    manager = login("manager", branch_ids=["a1", "a2"])
    administrateur = login("administrateur", branch_ids=["a1", "a2"])
    other_shop = login("business_owner", tenant="t2")
    stranger_store = login("manager", branch_ids=["a1"], store_limited=True)
    disabled = login("staff", active=False, branch_ids=["a1", "a2"], left=True)
    disabled_mgr = login("manager", active=False, branch_ids=["a1", "a2"], left=True)
    look_only = login("business_owner", claims={"view_only": True, "view_by": "team@fidclic.fr"})
    acting = login("business_owner", claims={"act_by": "admin@fidclic.fr", "view_by": "admin@fidclic.fr"})

    print("1. Team accounts can look, not export or erase")
    for name, headers in (("staff", staff), ("a manager", manager), ("an administrateur", administrateur),
                          ("a store-limited manager", stranger_store)):
        bc = card("a1")
        r = http("GET", f"/api/card/{bc}", headers=headers)
        check(f"{name} still gets « Voir sa carte » ({r.status_code})", r.status_code == 200)
        r = http("GET", f"/api/card/{bc}/my-data", headers=headers)
        check(f"{name} can't export ({r.status_code})", r.status_code == 403 and "marie" not in r.text.lower())
        r = forget(bc, headers)
        check(f"{name} can't erase ({r.status_code})", r.status_code == 403 and not erased(bc))

    print("\n2. The owner and FidClic can")
    for name, headers in (("the owner", owner), ("a FidClic super admin", admin), ("an admin in the account", acting)):
        bc = card()
        r = http("GET", f"/api/card/{bc}/my-data", headers=headers)
        check(f"{name} exports ({r.status_code})", r.status_code == 200 and r.json()["profile"]["email"] == "marie@exemple.fr")
        r = forget(bc, headers)
        check(f"{name} erases ({r.status_code})", r.status_code == 200 and erased(bc))
    bc = card("a2")
    r = http("GET", f"/api/card/{bc}/my-data?store=a1", headers=owner)
    check(f"the owner isn't limited by the store chosen in the menu ({r.status_code})", r.status_code == 200)

    print("\n3. The customer's own phone always can")
    bc = card()
    own = {"X-Card-Key": CO.key_for(bc)}
    r = http("GET", f"/api/card/{bc}/my-data", headers=own)
    check(f"export with the card's key ({r.status_code})", r.status_code == 200)
    r = forget(bc, own)
    check(f"erase with the card's key ({r.status_code})", r.status_code == 200 and erased(bc))

    print("\n4. The audit log says who did it")
    bc = card()
    forget(bc, {"X-Card-Key": CO.key_for(bc)})
    row = db.audit_logs.find_one({"action": "gdpr.forget_me", "target": db.customers.find_one({"barcode_id": bc})["id"]})
    check("the customer's own erase is the customer's", row and row["actor_type"] == "customer" and row["actor"] == bc)
    bc = card()
    cid = db.customers.find_one({"barcode_id": bc})["id"]
    http("GET", f"/api/card/{bc}/my-data", headers=owner)
    row = db.audit_logs.find_one({"action": "gdpr.export", "target": cid})
    check("an owner's export is the owner's", row and row["actor_type"] == "user" and row["actor"].startswith("business_owner"))
    forget(bc, owner)
    row = db.audit_logs.find_one({"action": "gdpr.forget_me", "target": cid})
    check("an owner's erase is the owner's", row and row["actor_type"] == "user" and row["actor"].startswith("business_owner"))

    print("\n5. Another shop gets nothing")
    bc = card()
    for method, path in (("GET", ""), ("GET", "/my-data")):
        r = http(method, f"/api/card/{bc}{path}", headers=other_shop)
        check(f"{method} {path or '/card'} refused ({r.status_code})", r.status_code == 403)
    r = forget(bc, other_shop)
    check(f"erase refused ({r.status_code})", r.status_code == 403 and not erased(bc))

    print("\n6. A disabled account has no card access at all")
    for name, headers in (("disabled staff", disabled), ("a disabled manager", disabled_mgr)):
        bc = card()
        r = http("GET", f"/api/card/{bc}", headers=headers)
        check(f"{name}: no « Voir sa carte » ({r.status_code})", r.status_code == 403)
        r = http("GET", f"/api/card/{bc}/my-data", headers=headers)
        check(f"{name}: no export ({r.status_code})", r.status_code == 403)
        r = forget(bc, headers)
        check(f"{name}: no erasure ({r.status_code})", r.status_code == 403 and not erased(bc))
        r = http("DELETE", f"/api/card/{bc}", headers=headers)
        check(f"{name}: can't delete the card ({r.status_code})",
              r.status_code == 403 and not db.customers.find_one({"barcode_id": bc}).get("card_deleted_at"))

    print("\n7. A look-only account changes nothing")
    bc = card()
    r = http("GET", f"/api/card/{bc}", headers=look_only)
    check(f"it can look at the card ({r.status_code})", r.status_code == 200)
    r = http("GET", f"/api/card/{bc}/my-data", headers=look_only)
    check(f"it can't export ({r.status_code})", r.status_code == 403)
    r = forget(bc, look_only)
    check(f"it can't erase ({r.status_code})", r.status_code == 403 and not erased(bc))
    r = http("DELETE", f"/api/card/{bc}", headers=look_only)
    check(f"it can't delete the card ({r.status_code})",
          r.status_code == 403 and not db.customers.find_one({"barcode_id": bc}).get("card_deleted_at"))
    r = http("POST", f"/api/card/{bc}/wallet-readded", headers=look_only)
    check(f"it can't change the card's state ({r.status_code})", r.status_code == 403)

    print("\n8. Active shop accounts keep what they had on the card")
    bc = card()
    r = http("DELETE", f"/api/card/{bc}", headers=staff)
    check(f"active staff can still delete a card, as decided on 2026-10-23 ({r.status_code})",
          r.status_code == 200 and db.customers.find_one({"barcode_id": bc}).get("card_deleted_at"))
    r = http("GET", f"/api/card/{card()}/my-data")
    check(f"no login, no key: refused ({r.status_code})", r.status_code == 403)
    r = http("POST", f"/api/card/{card()}/forget-me", json={"confirm": False}, headers=owner)
    check(f"erase still asks for confirmation ({r.status_code})", r.status_code == 422)
    r = http("GET", "/api/card/FT-NOPE/my-data", headers=owner)
    check(f"an unknown card is a 404 ({r.status_code})", r.status_code == 404)

    print("\n9. A suspended shop's logins have no card access")
    was = auth._tenant_check
    auth.set_tenant_check(lambda tid: "Ce compte est suspendu." if tid == "t1" else None)
    bc = card()
    for name, headers in (("the owner", owner), ("staff", staff)):
        r = http("GET", f"/api/card/{bc}/my-data", headers=headers)
        check(f"{name}: no export ({r.status_code})", r.status_code == 403)
        r = forget(bc, headers)
        check(f"{name}: no erasure ({r.status_code})", r.status_code == 403 and not erased(bc))
        r = http("DELETE", f"/api/card/{bc}", headers=headers)
        check(f"{name}: can't delete the card ({r.status_code})", r.status_code == 403)
    r = http("GET", f"/api/card/{bc}/my-data", headers={"X-Card-Key": CO.key_for(bc)})
    check(f"the customer's own phone still gets their data ({r.status_code})", r.status_code == 200)
    auth.set_tenant_check(was)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
