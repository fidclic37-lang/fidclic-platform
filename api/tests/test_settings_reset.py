"""
Paramètres › « Réinitialiser » — each tab goes back to how it was before its
last save (user, 2026-10-03).

    a save that changes something leaves a note; one that changes nothing doesn't
    « Réinitialiser » brings the newest note back, and drops it (again = one more back)
    nothing to undo → refused; the owner only (Préférences: each account, its own)
    Établissement: details, hours, closures, a point de vente's name — a point de
      vente added since stays
    Règles clients, Lien d'inscription (an old link name now taken is kept as is),
    Équipe (roles / access / on-off of accounts that still exist), Données,
    Notifications, Préférences, APIs (webhooks)
    Sécurité / Abonnement have none

Run: cd api && /usr/local/bin/python3 tests/test_settings_reset.py
"""
import asyncio
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx

    db = server.db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, tok, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers={"Authorization": "Bearer " + tok}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "corner", "name": "Le Corner", "plan": "vip", "sector": "cafe",
                           "subscription_status": "active", "postal_code": "37000", "city": "Tours",
                           "street": "12 Rue Nationale", "address": "12 Rue Nationale, 37000 Tours", "phone": "0247000000",
                           "branches": [{"id": "main", "name": "Centre", "is_main": True},
                                        {"id": "b2", "name": "Plumereau", "is_main": False}]})
    db.tenants.insert_one({"id": "t2", "slug": "voisin", "name": "Le Voisin", "plan": "silver"})
    db.users.insert_many([
        {"email": "o@c.fr", "role": "business_owner", "tenant_id": "t1"},
        {"email": "ali@c.fr", "role": "administrateur", "tenant_id": "t1", "branch_ids": ["main"], "active": True},
        {"email": "sara@c.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["main"], "active": True,
         "first_name": "Sara", "last_name": "B"},
    ])
    tok = lambda email, role: auth.create_access_token({"sub": email, "role": role, "tenant_id": "t1"})
    OWN, ALI, SARA = tok("o@c.fr", "business_owner"), tok("ali@c.fr", "administrateur"), tok("sara@c.fr", "manager")
    T = lambda: db.tenants.find_one({"id": "t1"})
    status = lambda sec, t=OWN: http("GET", f"/api/owner/settings-versions/{sec}", t).json()
    revert = lambda sec, t=OWN: http("POST", f"/api/owner/settings-versions/{sec}/revert", t)

    print("\nÉtablissement")
    check("nothing saved yet: nothing to reset", status("etablissement")["available"] is False)
    check("… and a reset is refused", revert("etablissement").status_code == 400)
    r = http("PUT", "/api/owner/etablissement", OWN, json={"business": {"name": "Le Corner Café", "description": "Torréfacteur"}})
    check("a save goes through as before", r.status_code == 200 and T()["name"] == "Le Corner Café", r.text[:200])
    st = status("etablissement")
    check("… and leaves a note: when and who", st["available"] and st["count"] == 1 and st["saved_at"] and st["saved_by"])
    http("PUT", "/api/owner/etablissement", OWN, json={"business": {"name": "Le Corner Café"}})
    check("a save that changes nothing leaves no note", status("etablissement")["count"] == 1)
    http("PUT", "/api/owner/etablissement", OWN, json={"legal": {"vat_number": "fr12345678901"}, "geo": {"radius_m": 300}})
    http("PUT", "/api/owner/settings/hours/weekly", OWN, json={"weekly_schedule": [
        {"day": d, "open_from": "08:00", "open_to": "18:00", "closed": d == "sunday"}
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]})
    http("PUT", "/api/owner/etablissement/stores/b2", OWN, json={"name": "Plumereau (Vieux-Tours)"})
    check("hours and a point de vente are noted in the same tab", status("etablissement")["count"] == 4)
    # a point de vente added since the last note
    db.tenants.update_one({"id": "t1"}, {"$push": {"branches": {"id": "b3", "name": "Gare", "is_main": False}}})
    r = revert("etablissement")
    t = T()
    check("reset 1: the point de vente's name comes back", r.status_code == 200
          and next(b for b in t["branches"] if b["id"] == "b2")["name"] == "Plumereau", r.text[:200])
    check("… a point de vente added since stays", any(b["id"] == "b3" for b in t["branches"]))
    check("… the hours (saved before) are still there", isinstance(t.get("weekly_schedule"), list))
    revert("etablissement")
    check("reset 2: the opening hours go back to none set", "weekly_schedule" not in T())
    revert("etablissement")
    t = T()
    check("reset 3: VAT and radius back as they were (absent)", "vat_number" not in t and "geo_radius_meters" not in t)
    revert("etablissement")
    t = T()
    check("reset 4: the name and description of the start", t["name"] == "Le Corner" and "description" not in t)
    check("… and nothing left to reset", status("etablissement")["available"] is False and revert("etablissement").status_code == 400)
    check("an administrateur may not reset it", revert("etablissement", ALI).status_code == 403
          and status("etablissement", ALI)["allowed"] is False)

    print("\nRègles clients")
    rules = http("GET", "/api/owner/customer-rules", OWN).json()["rules"]
    first = rules[0]["name"]
    edited = [dict(r) for r in rules]; edited[0]["name"] = "Mes habitués"
    r = http("PUT", "/api/owner/customer-rules", OWN, json={"rules": edited})
    check("a rule renamed", r.status_code == 200 and r.json()["rules"][0]["name"] == "Mes habitués", r.text[:200])
    revert("regles-clients")
    check("reset: its first name is back", http("GET", "/api/owner/customer-rules", OWN).json()["rules"][0]["name"] == first)

    print("\nLien d'inscription")
    http("PUT", "/api/owner/join-link/page", OWN, json={"title": "Rejoignez-nous", "subtitle": "", "benefits": ["Café offert"], "button": "Go"})
    http("PUT", "/api/owner/join-link/slug", OWN, json={"slug": "corner-cafe"})
    check("link name changed", T()["slug"] == "corner-cafe")
    revert("lien-inscription")
    check("reset: the old link name is back (still free)", T()["slug"] == "corner")
    revert("lien-inscription")
    check("reset: the page texts back to default", "join_page" not in T())
    http("PUT", "/api/owner/join-link/slug", OWN, json={"slug": "corner-2"})
    db.tenants.update_one({"id": "t2"}, {"$set": {"slug": "corner"}})           # someone took it meanwhile
    db.tenants.update_one({"id": "t1"}, {"$pull": {"previous_slugs": "corner"}})
    r = revert("lien-inscription")
    check("an old link name taken since: the current one is kept, and it is said",
          T()["slug"] == "corner-2" and r.json()["notes"] and "n'est plus disponible" in r.json()["notes"][0], r.text[:300])

    print("\nÉquipe & accès")
    users = {u["email"]: u for u in http("GET", "/api/owner/team-access", OWN).json().get("users", [])}
    sara_id = (users.get("sara@c.fr") or {}).get("id") or db.users.find_one({"email": "sara@c.fr"}).get("id") or "sara@c.fr"
    r = http("POST", f"/api/owner/team-access/users/{sara_id}/status", OWN, json={"active": False})
    check("an account paused", r.status_code == 200 and db.users.find_one({"email": "sara@c.fr"})["active"] is False, r.text[:200])
    db.users.insert_one({"email": "new@c.fr", "role": "staff", "tenant_id": "t1", "branch_ids": ["main"], "active": True})
    revert("equipe")
    check("reset: active again", db.users.find_one({"email": "sara@c.fr"})["active"] is True)
    check("… an account created since stays", db.users.find_one({"email": "new@c.fr"}) is not None)

    print("\nDonnées, Notifications, Préférences, APIs")
    http("PUT", "/api/owner/privacy", OWN, json={"retention": {"inactive_years": 2}, "cookie_notice": True})
    check("privacy saved", T()["privacy"]["retention"]["inactive_years"] == 2)
    revert("donnees")
    check("reset: privacy as it was (nothing set)", "privacy" not in T())
    http("PUT", "/api/owner/notifications/rules", OWN, json={"per_client_day": 2, "per_client_week": 5})
    revert("notifications")
    check("reset: sending limits as they were", "send_rules" not in T())
    http("PUT", "/api/me/preferences", SARA, json={"per_page": 50, "language": "en"})
    http("PUT", "/api/me/preferences", OWN, json={"per_page": 100})
    check("Préférences: each account has its own", status("preferences", SARA)["count"] == 1 and status("preferences")["count"] == 1)
    revert("preferences", SARA)
    sara = db.users.find_one({"email": "sara@c.fr"})
    check("a manager resets their own preferences", "preferences" not in sara)
    check("… not the owner's", db.users.find_one({"email": "o@c.fr"})["preferences"]["per_page"] == 100)
    db.webhooks.insert_one({"id": "h1", "tenant_id": "t1", "url": "https://hooks.example.com/a", "events": ["visit.created"], "active": True})
    r = http("PUT", "/api/owner/integrations/webhooks/h1", OWN, json={"url": "https://hooks.example.com/b", "events": ["customer.created"], "active": False})
    check("a webhook changed", r.status_code == 200 and db.webhooks.find_one({"id": "h1"})["url"].endswith("/b"), r.text[:200])
    revert("api")
    h = db.webhooks.find_one({"id": "h1"})
    check("reset: its address, events and on/off are back", h["url"].endswith("/a") and h["events"] == ["visit.created"] and h["active"] is True)

    print("\nLimits")
    for i in range(25):
        http("PUT", "/api/owner/etablissement", OWN, json={"business": {"description": f"v{i}"}})
    check("20 notes kept per tab at most", status("etablissement")["count"] == 20)
    check("Sécurité / Abonnement: no reset", status("securite")["supported"] is False
          and revert("abonnement").status_code == 404)
    check("another shop's notes are never read", http("GET", "/api/owner/settings-versions/etablissement",
          auth.create_access_token({"sub": "x@v.fr", "role": "business_owner", "tenant_id": "t2"})).json()["count"] == 0)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
