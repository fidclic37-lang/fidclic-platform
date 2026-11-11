"""
Super admin › Paramètres › Plateforme (user, 2026-11-11), PR 2 of 3:

    · Inscriptions ON/OFF (+ the message): off = no NEW business account,
      by e-mail or Google/Apple; sign-in and drafts already started go on.
    · Maintenance banner on every shop's dashboard, between its start and end.
    · Trial days (the same figure as Plan Limits, one place), the support
      inbox, the FidClic e-mail sender.
    · Shortcuts: the current values of the AI cap, Plan Limits, Sécurité and
      the Facturation issuer, each with its page.

Run: cd api && python3 -u tests/test_admin_platform_settings.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-platform-settings")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ.pop("SUPPORT_RECIPIENT_EMAIL", None)
os.environ["BREVO_API_KEY"] = "test-brevo"

passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    import server
    import auth
    import httpx
    from features import platform_config as PC, platform_access as PA
    from services import mailer, email_check

    db = server.db
    PA.forget()
    email_check.check = lambda e: {"ok": True}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def tok(email, role, tid=None):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}

    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin"},
        {"email": "look@fidclic.com", "role": "fidclic_team", "platform_role": "look"},
        {"email": "own@shop.fr", "role": "business_owner", "tenant_id": "s"},
    ])
    db.tenants.insert_one({"id": "s", "slug": "s", "name": "Shop", "is_active": True, "plan": "vip"})
    db.platform_roles.insert_one({"id": "look", "name": "Look", "perms": {"parametres": {"view": True, "edit": False}}})
    BOSS, LOOK, OWN = tok("boss@fidclic.com", "super_admin"), tok("look@fidclic.com", "fidclic_team"), tok("own@shop.fr", "business_owner", "s")
    URL = "/api/admin/settings/platform"

    # ------------------------------------------------------------------ who
    print("Qui peut")
    check("an owner: 403", http("GET", URL, headers=OWN).status_code == 403)
    check("« Voir »: reads", http("GET", URL, headers=LOOK).status_code == 200)
    check("« Voir » only cannot change (403)", http("PUT", URL, headers=LOOK, json={"signups_open": False}).status_code == 403)
    check("no token: 401/403", http("PUT", URL, json={"signups_open": False}).status_code in (401, 403))

    # ------------------------------------------------------------------ defaults
    print("\nPar défaut")
    j = http("GET", URL, headers=BOSS).json()
    s = j["settings"]
    check("sign-ups open by default", s["signups_open"] is True)
    check("no banner by default", s["banner"] is None)
    check("trial days = the trial plan's (30)", s["trial_days"] == 30, s)
    check("support inbox = the built-in one", s["support_email"] == "shuklaakshansh38@gmail.com", s)
    check("sender = the built-in one", s["sender_name"] == "FidClic" and "@" in s["sender_email"], s)
    pub = http("GET", "/api/platform/status").json()
    check("the public status says open, no banner (no sign-in needed)", pub == {"signups_open": True, "signups_message": None, "banner": None}, pub)

    # ------------------------------------------------------------------ refused values
    print("\nValeurs refusées")
    for body, label in [({"trial_days": 0}, "a 0-day trial"), ({"trial_days": 366}, "a 366-day trial"),
                        ({"support_email": "pas-un-email"}, "a support inbox that is not an e-mail"),
                        ({"sender_email": "x@"}, "a sender that is not an e-mail"),
                        ({"sender_name": "x" * 71}, "a sender name over 70 characters"),
                        ({"signups_message": "x" * 301}, "a closed-signup message over 300 characters"),
                        ({"banner": {"message": "", "level": "info"}}, "an empty banner"),
                        ({"banner": {"message": "Hi", "level": "panic"}}, "an unknown banner level"),
                        ({"banner": {"message": "Hi", "starts_at": "2026-11-12T10:00:00Z", "ends_at": "2026-11-12T09:00:00Z"}}, "a banner that ends before it starts"),
                        ({"nope": 1}, "an unknown setting")]:
        code = http("PUT", URL, headers=BOSS, json=body).status_code
        check(f"{label} → refused", code in (400, 422), code)

    # ------------------------------------------------------------------ sign-ups
    print("\nInscriptions")
    r = http("PUT", URL, headers=BOSS, json={"signups_open": False, "signups_message": "Lancement le 1er décembre !"})
    check("closing sign-ups is saved", r.status_code == 200 and r.json()["settings"]["signups_open"] is False, r.text[:200])
    check("…and journaled with what changed", db.audit_logs.find_one({"action": "platform.settings_update", "meta.changed": "signups_open"}))
    pub = http("GET", "/api/platform/status").json()
    check("the public status says closed, with the message", pub["signups_open"] is False and pub["signups_message"] == "Lancement le 1er décembre !", pub)
    reg = {"email": "new@biz.fr", "password": "Very-Strong-Pass-2026!", "first_name": "A", "last_name": "B",
           "phone": "0612345678", "accepted_terms": True}
    r = http("POST", "/api/auth/register", json=reg)
    check("a new business account is refused, with the message", r.status_code == 403 and "1er décembre" in r.text, (r.status_code, r.text[:200]))
    check("…nothing created", db.users.find_one({"email": "new@biz.fr"}) is None)
    from features import oauth as OA
    OA._db = db
    try:
        OA._upsert_user("google", "sub-1", "g@biz.fr", "G", "H", None, None)
        made = True
    except Exception as e:                                       # noqa: BLE001
        made = getattr(e, "status_code", None) != 403
    check("a NEW Google/Apple account is refused too", not made and db.users.find_one({"email": "g@biz.fr"}) is None)
    db.users.update_one({"email": "own@shop.fr"}, {"$set": {"hashed_password": auth.hash_password("Very-Strong-Pass-2026!")}})
    r = http("POST", "/api/auth/login", json={"email": "own@shop.fr", "password": "Very-Strong-Pass-2026!"})
    check("an existing business still signs in", r.status_code == 200, (r.status_code, r.text[:200]))
    http("PUT", URL, headers=BOSS, json={"signups_open": True})
    r = http("POST", "/api/auth/register", json=reg)
    check("re-opened: the account is created", r.status_code in (200, 201), (r.status_code, r.text[:200]))

    # ------------------------------------------------------------------ banner
    print("\nBandeau de maintenance")
    now = dt.datetime.now(UTC)
    later = {"message": "Maintenance ce soir 22:00–22:30", "level": "warning",
             "starts_at": (now + dt.timedelta(hours=2)).isoformat(), "ends_at": (now + dt.timedelta(hours=3)).isoformat()}
    r = http("PUT", URL, headers=BOSS, json={"banner": later})
    check("a banner is saved", r.status_code == 200 and r.json()["settings"]["banner"]["message"].startswith("Maintenance"), r.text[:200])
    check("…not shown before its start", http("GET", "/api/platform/status").json()["banner"] is None)
    live = {**later, "starts_at": (now - dt.timedelta(minutes=5)).isoformat()}
    http("PUT", URL, headers=BOSS, json={"banner": live})
    b = http("GET", "/api/platform/status").json()["banner"]
    check("…shown between its start and end, with its level and an id", b and b["message"].startswith("Maintenance") and b["level"] == "warning" and b.get("id"), b)
    http("PUT", URL, headers=BOSS, json={"banner": {**live, "ends_at": (now - dt.timedelta(minutes=1)).isoformat(),
                                                     "starts_at": (now - dt.timedelta(hours=1)).isoformat()}})
    check("…gone after its end", http("GET", "/api/platform/status").json()["banner"] is None)
    http("PUT", URL, headers=BOSS, json={"banner": {"message": "Sans fin", "level": "info"}})
    check("a banner with no dates shows until removed", (http("GET", "/api/platform/status").json()["banner"] or {}).get("message") == "Sans fin")
    http("PUT", URL, headers=BOSS, json={"banner": {"message": "<img src=x onerror=alert(1)>", "level": "info"}})
    check("the banner text is kept as text (the app shows it as text)",
          http("GET", "/api/platform/status").json()["banner"]["message"] == "<img src=x onerror=alert(1)>")
    http("PUT", URL, headers=BOSS, json={"banner": None})
    check("removed → no banner", http("GET", "/api/platform/status").json()["banner"] is None)

    # ------------------------------------------------------------------ trial, inbox, sender
    print("\nEssai, support, expéditeur")
    r = http("PUT", URL, headers=BOSS, json={"trial_days": 14})
    check("trial days saved", r.status_code == 200 and r.json()["settings"]["trial_days"] == 14, r.text[:200])
    from models import TRIAL_PLAN
    check("…in the same place as Plan Limits (the trial plan's override)",
          server.get_plan_features(TRIAL_PLAN)["trial_duration_days"] == 14)
    t = {}
    server._start_trial(t, TRIAL_PLAN)
    check("…a new trial now lasts 14 days", t["trial_duration_days"] == 14 and (t["trial_ends_at"] - t["trial_started_at"]).days == 14, t)
    other = (db.plan_settings.find_one({"plan": TRIAL_PLAN}) or {}).get("overrides") or {}
    check("…Plan Limits' other figures for that plan untouched", set(other) == {"trial_duration_days"}, other)

    r = http("PUT", URL, headers=BOSS, json={"support_email": "Support@FidClic.com"})
    check("support inbox saved (lower case)", r.json()["settings"]["support_email"] == "support@fidclic.com", r.json()["settings"])
    check("…the support form now writes there", PC.support_recipient() == "support@fidclic.com")
    r = http("PUT", URL, headers=BOSS, json={"sender_name": "FidClic Support", "sender_email": "hello@fidclic.com"})
    check("sender saved", r.json()["settings"]["sender_name"] == "FidClic Support")
    sent = []
    mailer._post = lambda payload, key: (sent.append(payload), {"messageId": "m1"})[1]
    mailer.send("own@shop.fr", "Hi", "<p>x</p>")
    check("…FidClic e-mails go out under it", sent and sent[0]["sender"] == {"email": "hello@fidclic.com", "name": "FidClic Support"}, sent)
    r = http("PUT", URL, headers=BOSS, json={"support_email": None, "sender_email": None, "sender_name": None})
    s = r.json()["settings"]
    check("empty = back to the built-in values", s["support_email"] == "shuklaakshansh38@gmail.com" and s["sender_name"] == "FidClic", s)

    # ------------------------------------------------------------------ shortcuts
    print("\nRaccourcis")
    db.platform_settings.update_one({"key": "invoice_issuer"}, {"$set": {"key": "invoice_issuer", "value": {"legal_name": "FidClic SAS"}}}, upsert=True)
    sc = {x["key"]: x for x in http("GET", URL, headers=LOOK).json()["shortcuts"]}
    check("four shortcuts: IA, Plan Limits, Sécurité, Facturation", set(sc) == {"ai", "plans", "security", "invoicing"}, list(sc))
    check("…each with its page", sc["ai"]["href"] == "/admin/ai/couts" and sc["plans"]["href"] == "/admin/plans"
          and sc["security"]["href"] == "/admin/securite/parametres" and sc["invoicing"]["href"] == "/admin/facturation", sc)
    check("…and its current value", "€" in sc["ai"]["value"] and "jours" in sc["plans"]["value"]
          and "tentatives" in sc["security"]["value"] and "FidClic SAS" in sc["invoicing"]["value"], {k: v["value"] for k, v in sc.items()})

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
