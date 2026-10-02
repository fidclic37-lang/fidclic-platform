"""
Bonus de bienvenue — one truth for every page (user, 2026-10-02).

It was edited on the Carte de fidélité and shown on Automatisations, and the
two read it differently: never saved = « Activé » + an English placeholder on
one page, « Désactivé » on the other. Now it is edited on Automatisations, and
the editor, the panel and the sign-up all read features/welcome_bonus.welcome_state.

Also on the Carte de fidélité: the QR code and the wallet can no longer be
switched off.

Run: cd api && /usr/local/bin/python3 tests/test_welcome_sync.py
"""
import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from features import auto_messages as AM

    db = server.db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, bearer=None, **kw):
        headers = {"Authorization": "Bearer " + bearer} if bearer else {}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "gold",
                           "subscription_status": "active", "created_at": now})
    db.users.insert_one({"email": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"})
    OWN = auth.create_access_token({"sub": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"})
    MAN = auth.create_access_token({"sub": "m@cafe.fr", "role": "manager", "tenant_id": "t1"})

    def both():
        er = http("GET", "/api/owner/earn-rules", OWN).json()
        am = http("GET", "/api/owner/auto-messages", OWN).json()["welcome"]
        return er, am

    n = [0]

    def signup():
        n[0] += 1
        c = {"id": f"c{n[0]}", "tenant_id": "t1", "name": f"Léa Martin{n[0]}", "barcode_id": f"FT-{n[0]:08d}",
             "points": 0, "visits": 0, "created_at": now}
        db.customers.insert_one(dict(c))
        return c, AM.welcome("t1", c)

    print("\nNever saved")
    er, am = both()
    check("the editor reads « désactivé »", er["enabled"] is False and er["active"] is False)
    check("and so does the Automatisations panel", am["enabled"] is False and am["active"] is False)
    check("no English placeholder anywhere", er["welcome_bonus_message"] == "" and am["message"] == "")
    check("a French suggestion is offered instead", "Bienvenue" in er["default_message"])
    _, sent = signup()
    check("and a new client gets nothing — as both pages say", sent is None)

    print("\nA placeholder saved by the old page")
    db.earn_rules.insert_one({"tenant_id": "t1", "enabled": True, "welcome_bonus_points": 0,
                              "welcome_bonus_message": "Welcome! Here are some bonus points to start.",
                              "points_per_visit": 15})
    er, am = both()
    check("is not read as a message", er["welcome_bonus_message"] == "" and am["message"] == "")
    check("so both pages say it sends nothing", er["active"] is False and am["active"] is False)
    _, sent = signup()
    check("and nothing in English reaches a client", sent is None)

    print("\nSaving")
    r = http("PUT", "/api/owner/earn-rules", OWN, json={**er, "enabled": True, "welcome_bonus_message": "  ",
                                                       "welcome_bonus_points": 0})
    check("on, with neither message nor points, is refused — it would send nothing",
          r.status_code == 400 and "rien ne sera envoyé" in r.json()["detail"])
    r = http("PUT", "/api/owner/earn-rules", OWN, json={**er, "enabled": True, "welcome_bonus_points": 50,
                                                       "welcome_bonus_message": "Bienvenue {first_name} !"})
    er, am = both()
    check("saved on: both pages say « actif »", er["active"] is True and am["active"] is True)
    check("with the same message and points",
          er["welcome_bonus_message"] == am["message"] == "Bienvenue {first_name} !"
          and er["welcome_bonus_points"] == am["points"] == 50)
    check("the other earn rules are kept", er["points_per_visit"] == 15)
    c, sent = signup()
    check("a new client gets that very message", sent and sent["message"].startswith("Bienvenue Léa"))
    check("and the points", db.customers.find_one({"id": c["id"]})["points"] == 50)
    check("only the owner changes it", http("PUT", "/api/owner/earn-rules", MAN, json=er).status_code == 403)

    http("PUT", "/api/owner/earn-rules", OWN, json={**er, "enabled": False})
    er, am = both()
    check("switched off: both pages say so", er["active"] is False and am["active"] is False and am["enabled"] is False)
    check("and the message is kept for later", am["message"] == "Bienvenue {first_name} !")
    _, sent = signup()
    check("a new client gets nothing", sent is None)
    check("reading again does not switch it back on", both()[1]["enabled"] is False)

    print("\nCarte de fidélité: the QR code and the wallet stay on")
    db.card_templates.insert_one({"tenant_id": "t1", "show_qr": False, "wallet_enabled": False})
    r = http("PUT", "/api/owner/card/settings", OWN, json={"card_name": "Ma carte", "show_qr": False, "wallet_enabled": False})
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check("a save switches both back on, whatever is sent", r.status_code == 200 and tpl["show_qr"] is True and tpl["wallet_enabled"] is True,
          r.text[:150])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
