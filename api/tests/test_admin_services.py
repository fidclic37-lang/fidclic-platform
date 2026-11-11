"""
Super admin › a business's services, one by one (user, 2026-11-11).

    « super admin se ek ek service hataa sake business ki… sab kuch business
      ka, cards, ia, campaigns, marketing, basically everything band kar sakein »

A trial's end switches nothing off. The super admin switches a service off
for one business, in the same gate as the plan's features (server.features_for
→ plan_limits), so it holds everywhere at once: the owner's pages and calls,
the automatic sends, the public signup page and the till's API. « Cartes » off
= no new card AND nothing on the old ones (no scan, tampons, points,
rewards). The owner reads « désactivé par FidClic », never an upgrade offer.
« Tout couper » switches every service off; the owner can still sign in.

    cd api && python3 tests/test_admin_services.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"
os.environ.setdefault("JWT_SECRET", "test-secret-admin-services")

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from fastapi import HTTPException
    from models import TokenData
    from features import admin_commerces as A, plan_limits as PL

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
    for tid, slug in (("t1", "lumiere"), ("t2", "voisin")):
        db.tenants.insert_one({"id": tid, "slug": slug, "name": f"Shop {tid}", "plan": "vip", "is_active": True,
                               "subscription_status": "trialing", "trial_started_at": now - dt.timedelta(days=40),
                               "trial_ends_at": now - dt.timedelta(days=10), "created_at": now - dt.timedelta(days=40)})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid, "active": True})
    OWN = auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})
    OWN2 = auth.create_access_token({"sub": "o@t2.fr", "role": "business_owner", "tenant_id": "t2"})
    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Alice", "barcode_id": "FT-ALICE001",
                             "visits": 3, "points": 30, "created_at": now - dt.timedelta(days=30)})

    def off(*keys):
        return A.set_services("t1", A.ServicesIn(off=list(keys)), token_data=ADMIN)

    def disabled(r):
        try:
            d = r.json().get("detail") or {}
        except Exception:
            return False
        return r.status_code == 403 and isinstance(d, dict) and d.get("code") == "SERVICE_DISABLED"

    print("\nA trial that ended switches nothing off")
    f = server.features_for(db.tenants.find_one({"id": "t1"}))
    check("every service of the plan is on", all(PL.allows(f, s["key"]) for s in PL.SERVICES))
    check("the campaigns page answers", not disabled(http("GET", "/api/owner/campaigns/page", OWN)))

    print("\nThe catalogue of switches")
    keys = [s["key"] for s in PL.SERVICES]
    check("cards, IA, campaigns, automations and the rest can each be switched",
          {"cards", "ai", "campaigns", "automations", "geo_proximity", "wallet", "referral", "segmentation",
           "advanced_analytics", "crm_advanced", "csv_export", "api_access"} <= set(keys))
    got = A.get_services("t1", token_data=ADMIN)
    check("the admin reads each one, all on", all(s["on"] for s in got["services"]) and got["all_off"] is False)

    print("\nOne service off: that one only")
    r = off("campaigns")
    check("saved", r["off"] == ["campaigns"])
    resp = http("GET", "/api/owner/campaigns/page", OWN)
    check("its page is refused with « désactivé par FidClic »", disabled(resp))
    det = resp.json()["detail"]
    check("… never an upgrade offer", det.get("upgrade") is None and "FidClic" in det.get("message", "")
          and "offre" not in det.get("message", ""))
    check("another service still answers (automations)", not disabled(http("GET", "/api/owner/automations", OWN)))
    check("another business is untouched", not disabled(http("GET", "/api/owner/campaigns/page", OWN2)))
    check("the scheduled sends stop too", PL.allows_tenant("t1", "campaigns") is False)
    pa = http("GET", "/api/owner/plan-access", OWN).json()
    check("the owner's screen is told: section locked, by FidClic",
          pa["sections"]["campaigns"] is False and pa["locked"]["campaigns"]["code"] == "SERVICE_DISABLED")
    check("a plan lock keeps the plan's own message",
          PL.locked({"label": "Starter", "campaigns": False}, "campaigns")["code"] == "PLAN_FEATURE_DISABLED")

    print("\nIA off")
    off("ai")
    check("the Copilote is refused", disabled(http("POST", "/api/owner/copilot/chat", OWN, json={"message": "?"})))
    from features import ai_meter as AM
    check("no AI money is spent for it (budget 0)", AM.limit_for("t1") == 0)
    check("… and no « limite IA atteinte » banner: it is off, not used up", AM.owner_alert("t1") is None)
    check("the campaigns are back on", not disabled(http("GET", "/api/owner/campaigns/page", OWN)))

    print("\nCartes off: no new card, nothing on the old ones")
    off("cards")
    check("the till's scan is refused", disabled(http("POST", "/api/owner/scan", OWN, json={"barcode_id": "FT-ALICE001"})))
    check("a reward cannot be used", disabled(http("POST", "/api/owner/rewards/redeem", OWN, json={"customer_id": "c1"})))
    check("points / tampons cannot be adjusted",
          disabled(http("POST", "/api/owner/clients/c1/ajustement", OWN, json={"points": 5})))
    check("a défi's reward cannot be used", disabled(http("POST", "/api/owner/defis/rewards/x/redeem", OWN)))
    n = db.customers.count_documents({"tenant_id": "t1"})
    r = http("POST", "/api/join/lumiere", json={"name": "Bob Neuf", "phone": "0612345678", "email": "bob@x.fr",
                                                "birth_date": "1990-05-04", "birthday": "05-04",
                                                "postal_code": "37000", "consent": True})
    check("a new signup is refused", disabled(r) and db.customers.count_documents({"tenant_id": "t1"}) == n)
    check("the signup page says it is closed", http("GET", "/api/join/lumiere").json().get("signups_closed") is True)
    check("another business still signs up", http("GET", "/api/join/voisin").json().get("signups_closed") is False)
    check("the welcome bonus cannot be claimed",
          disabled(http("POST", "/api/customer/welcome-bonus/claim", json={"tenant_slug": "lumiere", "barcode_id": "FT-ALICE001"})))
    key = http("POST", "/api/owner/integrations/keys", OWN, json={"name": "Caisse", "write": True}).json().get("key", "")
    check("(the till's key is made)", key.startswith("fc_live_"))
    async def till(path, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
            return await ac.post(path, json=body, headers={"Authorization": f"Bearer {key}"})
    run = lambda p, b: asyncio.get_event_loop().run_until_complete(till(p, b))       # noqa: E731
    check("the till's API: no visit", disabled(run("/api/v1/visits", {"customer": "FT-ALICE001", "amount": 10})))
    check("… no reward held", disabled(run("/api/v1/rewards/hold", {"customer": "FT-ALICE001"})))
    check("… no reward used", disabled(run("/api/v1/rewards/redeem", {"customer": "FT-ALICE001"})))
    check("no client imported from a file (each would be a new card)",
          disabled(http("POST", "/api/owner/clients/import/commit", OWN, json={"rows": []})))
    check("no « Ajoutez votre carte » invitation sent again",
          disabled(http("POST", "/api/owner/clients/invitations/relance", OWN, json={})))
    check("no card added back to a client's Wallet", disabled(http("POST", "/api/owner/clients/c1/card/readd", OWN)))
    check("the customer's data is kept", db.customers.find_one({"id": "c1"})["points"] == 30)

    print("\nGéolocalisation off: no proximity message")
    off("geo_proximity")
    from features import automations as AU
    db.automations.insert_one({"id": "g1", "tenant_id": "t1", "scenario": "geo", "status": "active", "name": "Géo",
                               "title": "Vous passez devant !", "body": "Venez !", "trigger": {}})
    said = AU._deliver("t1", db.automations.find_one({"id": "g1"}, {"_id": 0}), db.customers.find_one({"id": "c1"}, {"_id": 0}), {}, now)
    check("the proximity message is not sent", said is None
          and db.push_notifications.count_documents({"tenant_id": "t1", "automation_id": "g1"}) == 0)
    check("its page is refused", disabled(http("GET", "/api/owner/geo/overview", OWN)))

    print("\nTout couper")
    r = A.set_services("t1", A.ServicesIn(all_off=True), token_data=ADMIN)
    check("every service off", set(r["off"]) == set(keys))
    f = server.features_for(db.tenants.find_one({"id": "t1"}))
    check("the gate says so for each", not any(PL.allows(f, k) for k in keys))
    me = http("GET", "/api/auth/me", OWN)
    check("the owner can still sign in and read", me.status_code == 200)
    check("the automations stop sending", PL.allows_tenant("t1", "automations") is False)
    check("the Wallet cards stop updating", PL.allows_tenant("t1", "wallet") is False)
    r = A.set_services("t1", A.ServicesIn(off=[]), token_data=ADMIN)
    check("Tout rétablir: everything back", r["off"] == [] and not disabled(http("POST", "/api/owner/copilot/chat", OWN, json={"message": "?"})))

    print("\nWho may switch")
    check("an unknown service is refused", refused(lambda: off("teleport"), 400))
    check("an unknown business is refused",
          refused(lambda: A.set_services("nope", A.ServicesIn(off=[]), token_data=ADMIN), 404))
    check("an owner cannot call the admin route",
          http("PUT", "/api/admin/commerces/t1/services", OWN, json={"off": []}).status_code in (401, 403))
    db.platform_roles.insert_one({"id": "lecteur", "perms": {"commerces": {"view": True, "edit": False}}})
    db.users.insert_one({"email": "eve@fidclic.com", "role": "fidclic_team", "platform_role": "lecteur", "active": True})
    EVE = auth.create_access_token({"sub": "eve@fidclic.com", "role": "fidclic_team"})
    check("a team member who may only look cannot switch",
          http("PUT", "/api/admin/commerces/t1/services", EVE, json={"off": ["ai"]}).status_code == 403)
    check("… but may read them", http("GET", "/api/admin/commerces/t1/services", EVE).status_code == 200)
    off("campaigns", "ai")
    log = list(db.audit_log.find({"action": "admin.services", "tenant_id": "t1"})) or \
        list(db.audit_logs.find({"action": "admin.services", "tenant_id": "t1"}))
    check("every change is in the audit log, who and what", log and log[-1].get("meta", {}).get("off") == ["ai", "campaigns"])
    check("the super admin is never locked out of a business's pages",
          not disabled(http("GET", "/api/owner/campaigns/page", auth.create_access_token(
              {"sub": "boss@fidclic.com", "role": "super_admin"}))))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
