"""
CRM › Prospects › « Supprimer du CRM » a FidClic business (user, 2026-11-15):

    « businesses ko delete krne ka bhi option… idhar se jo businesses nhi
      chahiye unko hata sakun, lekin woh super admin se na hatein, bas idhar
      se hi hatein »

A business on FidClic leaves the CRM only: its prospect and its CRM history
go, the daily sync never brings it back — and the business itself is left
whole (Commerces, its plan, its customers, its login). A prospect that is
not on FidClic is deleted as before.

    cd api && python3 tests/test_crm_remove_prospect.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from models import TokenData
    from features import crm as C, admin_commerces as AC

    db = server.db
    C.init(db); AC.init(db)
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
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem"})
    now = dt.datetime.now(dt.timezone.utc)
    for tid, name in (("t1", "QA FidClic AI"), ("t2", "Royal Trim Test")):
        db.tenants.insert_one({"id": tid, "name": name, "slug": tid, "city": "Paris", "postal_code": "75001",
                               "plan": "vip", "is_active": True, "subscription_status": "trialing",
                               "onboarding_status": "done", "created_at": now - dt.timedelta(days=5),
                               "trial_ends_at": now + dt.timedelta(days=25)})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid, "active": True})
        db.customers.insert_one({"id": f"{tid}-c", "tenant_id": tid, "name": "Client", "visits": 2, "created_at": now})
    C.sync_tenants()
    p1 = db.crm_prospects.find_one({"tenant_id": "t1"})
    check("(the business is in the CRM after the sync)", bool(p1))
    C._log(p1["id"], "note", "Appelé lundi", "boss@fidclic.com")
    db.crm_prospects.insert_one({"id": "free", "name": "Boulangerie pas encore cliente", "stage": "a_contacter",
                                 "tenant_id": None, "created_at": now, "updated_at": now})
    tenant_before = db.tenants.find_one({"id": "t1"}, {"_id": 0})

    print("\nA FidClic business leaves the CRM")
    r = C.delete_prospect(p1["id"], token_data=ADMIN)
    check("removed from the CRM", r.get("deleted") is True and not db.crm_prospects.find_one({"id": p1["id"]}))
    check("its CRM history goes with it", db.crm_activities.count_documents({"prospect_id": p1["id"]}) == 0)
    check("not in the prospects list", p1["id"] not in {x["id"] for x in C.list_prospects(token_data=ADMIN)["rows"]})

    print("\n… and only the CRM")
    check("the business is left exactly as it was", db.tenants.find_one({"id": "t1"}, {"_id": 0}) == tenant_before)
    check("its customers and its owner stay", db.customers.count_documents({"tenant_id": "t1"}) == 1
          and db.users.count_documents({"tenant_id": "t1"}) == 1)
    check("still in Super admin › Commerces", "t1" in {x["id"] for x in AC.list_commerces(token_data=ADMIN)["rows"]})

    print("\nThe sync never brings it back")
    C.sync_tenants()
    check("not re-created", not db.crm_prospects.find_one({"tenant_id": "t1"}))
    check("not linked to another prospect by its name either",
          not db.crm_prospects.find_one({"name": "QA FidClic AI"}))
    check("the other business is still synced", bool(db.crm_prospects.find_one({"tenant_id": "t2"})))

    print("\nA prospect not on FidClic: deleted as before")
    check("deleted", C.delete_prospect("free", token_data=ADMIN).get("deleted") is True
          and not db.crm_prospects.find_one({"id": "free"}))

    print("\nWho may")
    p2 = db.crm_prospects.find_one({"tenant_id": "t2"})
    check("an unknown prospect: 404", refused(lambda: C.delete_prospect("nope", token_data=ADMIN), 404))
    log = list(db.audit_log.find({"action": "crm.prospect_removed"})) or list(db.audit_logs.find({"action": "crm.prospect_removed"}))
    check("the removal of a FidClic business is in the audit log, with the business",
          log and log[0].get("tenant_id") == "t1")
    import inspect
    check("only the super admin (require_super)", "require_super" in inspect.getsource(C.delete_prospect))
    check("(the other business untouched)", bool(p2))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
