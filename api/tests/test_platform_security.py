"""
Super admin › Sécurité — roles and permissions enforced by the server (Voir /
Modifier per section, CRM included), team users, logins (lockout, allowed
countries, new country), the automatic activity journal, and the figures.

Everything goes through the real app over HTTP, the way the browser does.

Run: cd api && /usr/local/bin/python3 tests/test_platform_security.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    from features import platform_access as PA, platform_security as PS

    db = server.db
    PA.init(db)
    PS.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    import asyncio
    import httpx

    class _Client:
        """Requests straight into the app (the installed TestClient and httpx
        disagree on versions). No cookies are kept: each call carries its token."""
        def _go(self, method, url, **kw):
            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                    return await ac.request(method, url, **kw)
            return asyncio.get_event_loop().run_until_complete(run())

        def get(self, url, **kw): return self._go("GET", url, **kw)
        def post(self, url, **kw): return self._go("POST", url, **kw)
        def put(self, url, **kw): return self._go("PUT", url, **kw)
        def delete(self, url, **kw): return self._go("DELETE", url, **kw)

    def client():
        return _Client()

    def tok(email, role):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role})}

    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem", "last_name": "B.", "hashed_password": auth.hash_password("Boss!2026x")},
        {"email": "sofia@fidclic.com", "role": "fidclic_team", "platform_role": "analyste", "first_name": "Sofia", "last_name": "R.",
         "hashed_password": auth.hash_password("Sofia!2026x")},
        {"email": "adm@fidclic.com", "role": "fidclic_team", "platform_role": "administrateur", "first_name": "Admin", "last_name": "F."},
        {"email": "old.sales@fidclic.com", "role": "commercial", "first_name": "Karim", "last_name": "D."},
        {"email": "owner@cafe.fr", "role": "business_owner", "tenant_id": "t1", "hashed_password": auth.hash_password("Owner!2026x")},
    ])
    db.tenants.insert_one({"id": "t1", "name": "Café Lumière", "plan": "gold", "is_active": True})
    BOSS, SOFIA, ADM, OLD = (tok("boss@fidclic.com", "super_admin"), tok("sofia@fidclic.com", "fidclic_team"),
                             tok("adm@fidclic.com", "fidclic_team"), tok("old.sales@fidclic.com", "commercial"))
    c = client()

    print("\nRoles")
    roles = {r["id"]: r for r in c.get("/api/admin/security/roles", headers=BOSS).json()["roles"]}
    check("the five of the mockup + Commercial", set(roles) == {"super_admin", "administrateur", "analyste", "support", "finance", "commercial"})
    mods = [m["key"] for m in c.get("/api/admin/security/roles", headers=BOSS).json()["modules"]]
    check("CRM is one of the sections, with Voir and Modifier", "crm" in mods and set(roles["commercial"]["perms"]["crm"]) == {"view", "edit"})
    check("Super Admin: everything, locked", roles["super_admin"]["locked"] and all(v["view"] and v["edit"] for v in roles["super_admin"]["perms"].values()))
    check("users counted per role", roles["analyste"]["users"] == 1 and roles["commercial"]["users"] == 1)

    print("\nThe server enforces the switches")
    check("Analyste: Analytics yes", c.get("/api/admin/analytics", headers=SOFIA).status_code == 200)
    check("Analyste: Commerces no", c.get("/api/admin/commerces", headers=SOFIA).status_code == 403)
    check("Analyste: CRM no", c.get("/api/crm/meta", headers=SOFIA).status_code == 403)
    check("Administrateur: sees and changes Commerces", c.get("/api/admin/commerces", headers=ADM).status_code == 200
          and c.put("/api/admin/commerces/t1", json={"city": "Tours"}, headers=ADM).status_code == 200)
    check("Administrateur: Plan Limits no", c.get("/api/admin/plans", headers=ADM).status_code == 403)
    check("the old Commercial account keeps its CRM", c.get("/api/crm/meta", headers=OLD).status_code == 200
          and c.get("/api/admin/commerces", headers=OLD).status_code == 403)
    check("a business owner never gets in", c.get("/api/admin/commerces", headers=tok("owner@cafe.fr", "business_owner")).status_code == 403)
    r = c.get("/api/admin/commerces", headers=SOFIA)
    check("a clear message", "Commerces" in r.json()["detail"])

    print("\nCustom role, Voir without Modifier")
    new = c.post("/api/admin/security/roles", json={"name": "Stagiaire CRM", "perms": {"crm": {"view": True, "edit": False},
                                                                                         "commerces": {"edit": True}}}, headers=BOSS)
    check("created by the super admin", new.status_code == 200 and new.json()["perms"]["commerces"] == {"view": True, "edit": True})
    rid = new.json()["id"]
    check("only the super admin creates roles", c.post("/api/admin/security/roles", json={"name": "X"}, headers=ADM).status_code == 403)
    u = c.post("/api/admin/security/users", json={"email": "Stag@FidClic.com", "first_name": "Inès", "last_name": "T.", "role_id": rid}, headers=BOSS)
    check("user added with a temporary password", u.status_code == 200 and u.json()["password"])
    STAG = tok("stag@fidclic.com", "fidclic_team")
    check("Voir on CRM: reads", c.get("/api/crm/prospects", headers=STAG).status_code == 200)
    check("no Modifier on CRM: cannot add", c.post("/api/crm/prospects", json={"name": "Test"}, headers=STAG).status_code == 403)
    c.put(f"/api/admin/security/roles/{rid}", json={"perms": {"crm": {"view": True, "edit": True}}}, headers=BOSS)
    check("switch turned on: applies at once", c.post("/api/crm/prospects", json={"name": "Test Resto"}, headers=STAG).status_code == 200)
    me = c.get("/api/auth/me", headers=STAG).json()
    check("/auth/me gives the role and its permissions", me["platform_role_name"] == "Stagiaire CRM" and me["permissions"]["crm"]["edit"])
    check("a role with users cannot be deleted", c.delete(f"/api/admin/security/roles/{rid}", headers=BOSS).status_code == 409)
    check("base roles cannot be deleted", c.delete("/api/admin/security/roles/analyste", headers=BOSS).status_code == 400)
    check("Super Admin's access cannot be reduced", c.put("/api/admin/security/roles/super_admin", json={"perms": {}}, headers=BOSS).status_code == 400)

    print("\nUsers")
    check("Sécurité: Administrateur may look", c.get("/api/admin/security/users", headers=ADM).status_code == 200)
    check("…but not change anyone", c.put("/api/admin/security/users/sofia@fidclic.com", json={"role_id": "super_admin"}, headers=ADM).status_code == 403)
    check("same email twice refused", c.post("/api/admin/security/users", json={"email": "stag@fidclic.com", "role_id": "support"}, headers=BOSS).status_code == 409)
    check("cannot change one's own role", c.put("/api/admin/security/users/boss@fidclic.com", json={"role_id": "support"}, headers=BOSS).status_code == 400)
    check("cannot switch oneself off", c.put("/api/admin/security/users/boss@fidclic.com", json={"active": False}, headers=BOSS).status_code == 400)
    db.user_sessions.insert_one({"sid": "s1", "email": "stag@fidclic.com", "revoked_at": None, "last_seen": PS._now()})
    c.put("/api/admin/security/users/stag@fidclic.com", json={"active": False}, headers=BOSS)
    check("switched off: sessions end, access refused", db.user_sessions.find_one({"sid": "s1"})["revoked_at"] is not None
          and c.get("/api/crm/prospects", headers=STAG).status_code == 401)
    c.put("/api/admin/security/users/stag@fidclic.com", json={"active": True, "role_id": "support"}, headers=BOSS)
    check("role changed: the new role's access", c.get("/api/crm/prospects", headers=STAG).status_code == 403
          and c.get("/api/admin/commerces", headers=STAG).status_code == 200)
    rows = {r["email"]: r for r in c.get("/api/admin/security/users", headers=BOSS).json()["rows"]}
    check("list: role name, status", rows["sofia@fidclic.com"]["role_name"] == "Analyste" and rows["stag@fidclic.com"]["active"])
    check("empty role deleted", c.delete(f"/api/admin/security/roles/{rid}", headers=BOSS).status_code == 200)

    print("\nLogins: lockout")
    def login(email, pw, cc="FR", city="Paris", cl=None):
        cl = cl or client()
        return cl.post("/api/auth/login", json={"email": email, "password": pw}, headers={"x-vercel-ip-country": cc, "x-vercel-ip-city": city})
    check("a good login", login("sofia@fidclic.com", "Sofia!2026x").status_code == 200)
    for _ in range(5):
        login("sofia@fidclic.com", "wrong")
    r = login("sofia@fidclic.com", "Sofia!2026x")
    check("5 wrong passwords: blocked, even with the right one", r.status_code == 429 and "bloqué" in r.json()["detail"])
    check("recorded as failed / blocked", db.platform_logins.count_documents({"email": "sofia@fidclic.com", "reason": "bad_password"}) == 5
          and db.platform_logins.find_one({"email": "sofia@fidclic.com", "reason": "locked"}))
    c.post("/api/admin/security/users/sofia@fidclic.com/unlock", headers=BOSS)
    check("unlocked by the super admin", login("sofia@fidclic.com", "Sofia!2026x").status_code == 200)
    check("a business owner's logins are not the team's", login("owner@cafe.fr", "Owner!2026x").status_code == 200
          and not db.platform_logins.find_one({"email": "owner@cafe.fr"}))

    print("\nLogins: countries")
    r = login("sofia@fidclic.com", "Sofia!2026x", cc="MA", city="Casablanca")
    check("a new country goes through, marked suspicious", r.status_code == 200
          and db.platform_logins.find_one({"email": "sofia@fidclic.com", "cc": "MA"})["suspicious"])
    alerts = c.get("/api/admin/security/alerts", headers=BOSS).json()["alerts"]
    check("the super admin's bell says so", alerts and alerts[0]["title"].startswith("Connexion suspecte"))
    bad = c.put("/api/admin/security/settings", json={"allowed_countries": ["MA"]}, headers={**BOSS, "x-vercel-ip-country": "FR"})
    check("cannot lock oneself out (own country missing)", bad.status_code == 400)
    ok = c.put("/api/admin/security/settings", json={"allowed_countries": ["fr", "DZ", "MA", "zz9"], "max_failed": 5, "lock_minutes": 15},
               headers={**BOSS, "x-vercel-ip-country": "FR"})
    check("allowed countries saved, cleaned", ok.status_code == 200 and ok.json()["allowed_countries"] == ["DZ", "FR", "MA"])
    r = login("sofia@fidclic.com", "Sofia!2026x", cc="TR", city="Istanbul")
    check("any other country: refused", r.status_code == 403 and db.platform_logins.find_one({"cc": "TR"})["blocked"])
    check("country unknown (no header): not blocked", client().post("/api/auth/login", json={"email": "sofia@fidclic.com", "password": "Sofia!2026x"}).status_code == 200)
    check("business owners are not concerned", login("owner@cafe.fr", "Owner!2026x", cc="TR").status_code == 200)

    print("\nJournal d'activité")
    j0 = db.audit_logs.count_documents({"action": "platform.request"})
    c.post("/api/crm/prospects", json={"name": "Le Petit Zinc"}, headers=BOSS)
    auto = db.audit_logs.find_one({"action": "platform.request", "meta.path": "/api/crm/prospects", "actor": "boss@fidclic.com"})
    check("a change with no audit of its own is journaled automatically", auto and auto["actor"] == "boss@fidclic.com"
          and auto["meta"]["status"] == 200)
    c.post("/api/admin/commerces/t1/suspend", json={"reason": "test"}, headers=BOSS)
    check("…but never twice when the endpoint audits itself", db.audit_logs.count_documents({"action": "platform.request", "meta.path": "/api/admin/commerces/t1/suspend"}) == 0
          and db.audit_logs.find_one({"action": "admin.commerce_suspend"}))
    c.post("/api/admin/commerces/t1/reactivate", headers=SOFIA)
    refused = db.audit_logs.find_one({"action": "platform.request", "meta.path": "/api/admin/commerces/t1/reactivate"})
    check("a refused attempt is journaled as refused", refused and refused["meta"]["status"] == 403)
    j = c.get("/api/admin/security/journal?per_page=100", headers=BOSS).json()
    labels = {r["label"] for r in j["rows"]}
    check("French labels", {"Création — CRM de prospection", "Suspension d'un commerce", "Ajout d'un utilisateur"} <= labels)
    check("status column", {"Succès", "Refusé"} <= {r["status"] for r in j["rows"]})
    check("filter by user", all(r["email"] == "sofia@fidclic.com" for r in c.get("/api/admin/security/journal?user=sofia@fidclic.com", headers=BOSS).json()["rows"]))
    check("CSV export", c.get("/api/admin/security/journal/export", headers=BOSS).text.lstrip("﻿").startswith("Date;Utilisateur"))
    check("reads are not journaled", db.audit_logs.count_documents({"action": "platform.request", "meta.method": "GET"}) == 0)

    print("\nFigures")
    ov = c.get("/api/admin/security/overview", headers=BOSS).json()
    k = {x["key"]: x["value"] for x in ov["cards"]}
    check("five figures", k["users"] == 5 and k["logins"] >= 4 and k["suspicious"] >= 2 and k["failed"] >= 5 and k["actions"] > 0)
    check("where logins come from", {o["label"] for o in ov["origins"]} >= {"Maroc"})
    check("actions by kind", {a["label"] for a in ov["actions_split"]} >= {"Utilisateurs", "Commerces"})
    check("logins per day", sum(d["logins"] for d in ov["logins_by_day"]) == k["logins"])
    check("recent logins show the blocked one", any(r["status"] == "Bloquée" for r in c.get("/api/admin/security/logins?status=blocked", headers=BOSS).json()["rows"]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
