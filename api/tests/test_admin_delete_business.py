"""
Super admin › « Supprimer » a business (user, 2026-11-11):

    « businesses ko permanently delete krne ka option… delete hone k baad woh
      deleted section mein dikhe, lekin database mein us business ka data
      rehna chahiye, woh n delete ho »

Deleted = gone from every list, count and cron of the platform, its team
signed out and refused, its customers' cards and signup closed, every service
off — and shown only under « Supprimés ». Not one document is removed: the
business, its users, customers, visits and campaigns stay in the database.
The super admin types the business's name to confirm.

    cd api && python3 tests/test_admin_delete_business.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"
os.environ.setdefault("JWT_SECRET", "test-secret-admin-delete")

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from fastapi import HTTPException
    from models import TokenData
    from features import admin_commerces as A, plan_limits as PL, onboarding as OB

    db = server.db
    A.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def http(method, url, token=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                h = {"Authorization": f"Bearer {token}"} if token else {}
                return await ac.request(method, url, headers=h, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def refused(fn, code):
        try:
            fn(); return False
        except HTTPException as e:
            return e.status_code == code

    now = dt.datetime.now(dt.timezone.utc)
    for tid, slug, name in (("t1", "lumiere", "Café Lumière"), ("t2", "voisin", "Le Voisin")):
        db.tenants.insert_one({"id": tid, "slug": slug, "name": name, "plan": "gold", "is_active": True,
                               "subscription_status": "active", "onboarding_status": "done",
                               "created_at": now - dt.timedelta(days=400)})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid, "active": True})
        db.customers.insert_many([{"id": f"{tid}-c{i}", "tenant_id": tid, "name": f"Client {i}", "visits": 2,
                                   "barcode_id": f"FT-{tid}{i:04d}", "created_at": now - dt.timedelta(days=30)}
                                  for i in range(3)])
        db.visits.insert_many([{"id": f"{tid}-v{i}", "tenant_id": tid, "customer_id": f"{tid}-c{i}",
                                "amount_paid": 10.0, "visit_time": now - dt.timedelta(days=2)} for i in range(3)])
        db.campaigns.insert_one({"id": f"{tid}-camp", "tenant_id": tid, "name": "Promo", "status": "sent", "sent_at": now})
    OWN = auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})
    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    ADMIN_TOK = auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin"})
    before = {c: db[c].count_documents({"tenant_id": "t1"}) for c in ("users", "customers", "visits", "campaigns")}

    print("\nThe name must be typed to confirm")
    check("a wrong name is refused", refused(lambda: A.supprimer("t1", A.SupprimerIn(confirm_name="Café", reason="test"),
                                                                    token_data=ADMIN), 400))
    check("nothing happened", not db.tenants.find_one({"id": "t1"}).get("deleted_at"))
    check("an unknown business is refused",
          refused(lambda: A.supprimer("nope", A.SupprimerIn(confirm_name="x", reason="test"), token_data=ADMIN), 404))

    print("\nDeleted")
    r = A.supprimer("t1", A.SupprimerIn(confirm_name="  café lumière ", reason="Fermeture du commerce"), token_data=ADMIN)
    t = db.tenants.find_one({"id": "t1"})
    check("marked deleted, by whom and why", t.get("deleted_at") and t.get("deleted_by") == "boss@fidclic.com"
          and t.get("deletion_reason") == "Fermeture du commerce")
    check("every service off", set(t.get("services_off") or []) == set(PL.SERVICE_KEYS))
    check("not one document removed",
          {c: db[c].count_documents({"tenant_id": "t1"}) for c in before} == before and db.tenants.find_one({"id": "t1"}))
    check("deleting it twice is refused",
          refused(lambda: A.supprimer("t1", A.SupprimerIn(confirm_name="Café Lumière", reason="encore"), token_data=ADMIN), 409))

    print("\nGone from the platform")
    lst = A.list_commerces(token_data=ADMIN)
    check("not in the list of businesses", "t1" not in {x["id"] for x in lst["rows"]} and lst["total"] == 1)
    check("not in the cards' total", next(c for c in lst["cards"] if c["key"] == "total")["value"] == 1)
    gone = A.list_commerces(tab="supprime", token_data=ADMIN)
    check("shown under « Supprimés », with its date", [x["id"] for x in gone["rows"]] == ["t1"]
          and gone["rows"][0]["deleted_at"] and gone["rows"][0]["status"] == "supprime")
    check("the tab is counted", lst["counts"]["supprime"] == 1)
    check("its page still opens for the super admin", http("GET", "/api/admin/commerces/t1", ADMIN_TOK).status_code == 200)
    check("the other business is untouched", "t2" in {x["id"] for x in lst["rows"]}
          and not db.tenants.find_one({"id": "t2"}).get("deleted_at"))

    print("\nIts team and its customers")
    A.forget("t1")
    check("its team is signed out and refused", http("GET", "/api/auth/me", OWN).status_code in (401, 403))
    check("the reason says deleted", "supprimé" in (A.is_suspended("t1") or ""))
    j = http("GET", "/api/join/lumiere")
    check("its signup page is closed (« Programme terminé », like a résilié one)",
          j.status_code == 410 and j.json().get("code") == "PROGRAM_CLOSED")
    check("… and no signup goes through", http("POST", "/api/join/lumiere", json={}).status_code in (403, 410))
    check("its customers' cards stop", "t1" in A.closed_programs()["ids"])

    print("\nNo cron ever removes it")
    OB.purge_abandoned_signups(now + dt.timedelta(days=400))
    check("the draft purge leaves it and its data", db.tenants.find_one({"id": "t1"})
          and db.customers.count_documents({"tenant_id": "t1"}) == before["customers"])

    print("\nWho may delete")
    check("an owner cannot", http("POST", "/api/admin/commerces/t2/supprimer", auth.create_access_token(
        {"sub": "o@t2.fr", "role": "business_owner", "tenant_id": "t2"}), json={"confirm_name": "Le Voisin", "reason": "x"}).status_code in (401, 403))
    db.platform_roles.insert_one({"id": "lecteur", "perms": {"commerces": {"view": True, "edit": False}}})
    db.users.insert_one({"email": "eve@fidclic.com", "role": "fidclic_team", "platform_role": "lecteur", "active": True})
    check("a team member who may only look cannot", http("POST", "/api/admin/commerces/t2/supprimer", auth.create_access_token(
        {"sub": "eve@fidclic.com", "role": "fidclic_team"}), json={"confirm_name": "Le Voisin", "reason": "x"}).status_code == 403)
    log = list(db.audit_log.find({"action": "admin.commerce_delete"})) or list(db.audit_logs.find({"action": "admin.commerce_delete"}))
    check("the deletion is in the audit log", log and log[0].get("tenant_id") == "t1")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
