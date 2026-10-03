"""
Offre Franchise — sur devis: in the catalogue without a price, a request
from the owner, the super admin's own terms per franchise, and those terms
actually applying (limits, revenue, next plan).

Run: cd api && /usr/local/bin/python3 tests/test_franchise.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import HTTPException
    from models import TokenData
    from features import franchise as F
    from features import invoices as I
    from features import plans_public as PP
    from features import billing as BL

    db = server.db
    F.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def refused(fn, code):
        try:
            fn(); return False
        except HTTPException as e:
            return e.status_code == code

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    OWNER = TokenData(email="o@burger.fr", role="business_owner", tenant_id="t1")
    db.tenants.insert_one({"id": "t1", "name": "Burger Republic", "plan": "vip", "subscription_status": "active",
                           "branches": [{"id": "main"}, {"id": "b2"}, {"id": "b3"}]})
    db.users.insert_one({"email": "o@burger.fr", "role": "business_owner", "tenant_id": "t1"})

    print("\nCatalogue")
    check("Franchise is a plan, labelled", server.get_plan_features("franchise")["label"] == "Franchise")
    pub = PP.public_plans()
    check("public site: self-serve prices unchanged, Franchise « sur devis » apart",
          [p["key"] for p in pub["plans"]] == ["silver", "gold", "vip"] and pub["quote_plans"][0]["price_monthly"] is None)
    ov = I.billing_overview(token_data=OWNER)
    fr = next(p for p in ov["catalogue"] if p["key"] == "franchise")
    check("Abonnement page: a Franchise card with no price", fr["on_quote"] and fr["price"] is None and fr["features"])
    check("self-serve checkout refuses it, saying why", refused(lambda: BL.create_checkout(BL.CheckoutRequest(plan="franchise"), token_data=OWNER), 400))
    check("Pro AI's next plan is Franchise, price on quote", server.NEXT_PLAN["vip"] == "franchise"
          and server.NEXT_PLAN["silver"] == "gold")

    print("\nRequest")
    r1 = server.request_upgrade(server.UpgradeRequest(requested_plan="franchise", message="3 restaurants"), token_data=OWNER)
    r2 = server.request_upgrade(server.UpgradeRequest(requested_plan="franchise", message="3 restaurants, bientôt 5"), token_data=OWNER)
    check("one open request, not two", r1["id"] == r2["id"] and db.upgrade_requests.count_documents({}) == 1)
    check("its message is kept up to date", db.upgrade_requests.find_one({})["message"] == "3 restaurants, bientôt 5")
    check("the page shows « demande envoyée »", next(p for p in I.billing_overview(token_data=OWNER)["catalogue"]
                                                    if p["key"] == "franchise")["requested"])
    check("the super admin sees it", len(F.franchise_overview(token_data=ADMIN)["requests"]) == 1)

    print("\nTerms")
    check("unknown business", refused(lambda: F.set_franchise("nope", F.TermsIn(price=450, establishments=5), token_data=ADMIN), 404))
    F.set_franchise("t1", F.TermsIn(price=450, establishments=5, max_customers=30000, notes="Réseau Loire"), token_data=ADMIN)
    t = db.tenants.find_one({"id": "t1"})
    check("switched to Franchise with its terms", t["plan"] == "franchise" and t["franchise_terms"]["price"] == 450)
    check("the request is closed", db.upgrade_requests.find_one({})["status"] == "completed")
    f = server.features_for(t)
    check("its own limits apply", f["establishments"] == 5 and f["max_customers"] == 30000 and f["multi_branch"])
    check("unset limits keep the Franchise defaults", f["staff_accounts"] == server.PLAN_FEATURES["franchise"]["staff_accounts"])
    check("revenue counts the agreed price", server.tenant_price(t) == 450)
    ov = I.billing_overview(token_data=OWNER)
    check("the owner sees their plan and price", ov["plan"]["label"] == "Franchise" and ov["plan"]["price"] == 450)
    check("…and the franchise card shows their price", next(p for p in ov["catalogue"] if p["key"] == "franchise")["price"] == 450)
    check("franchises listed for the super admin", F.franchise_overview(token_data=ADMIN)["franchises"][0]["effective"]["price"] == 450)
    check("audited", db.audit_logs.find_one({"action": "admin.franchise_terms"}) is not None
          or db.audit_log.find_one({"action": "admin.franchise_terms"}) is not None)

    print("\nOther plans unchanged")
    check("Starter / Pro / Pro AI prices", [server.get_plan_features(k)["price"] for k in ("silver", "gold", "vip")] == [33, 65, 108])
    check("features_for on a normal plan = the plan", server.features_for({"plan": "gold"})["max_customers"]
          == server.get_plan_features("gold")["max_customers"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
