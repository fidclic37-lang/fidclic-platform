"""
Super admin › Paramètres › Mes paramètres (user, 2026-11-11), PR 3 of 3 —
for every member of FidClic's team (super admin, team roles, commercial):

    · Profil: nom, prénom, téléphone, photo
    · Mot de passe + 2FA (the same rules as the shops' accounts)
    · Sessions: where I am signed in, « Déconnecter les autres »
    · Mes alertes: per alert type, « email » (bell + e-mail) or « bell » only —
      new business, support, security, FidClic IA, impayé, my team tasks.
      Defaults keep today's behaviour (FidClic IA e-mails the super admins).

Run: cd api && python3 -u tests/test_admin_me.py
"""
import asyncio
import base64
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-admin-me")
os.environ.setdefault("DISABLE_SEED", "1")
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
    from features import team_alerts as TA, platform_access as PA, security_page as SP
    from services import mailer

    db = server.db
    PA.forget()
    mails = []
    mailer.send = lambda to, subject, html, text=None, to_name=None, reply_to=None: (mails.append((to, subject)), {"sent": True})[1]

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    PW = "Very-Strong-Pass-2026!"
    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Akshansh", "hashed_password": auth.hash_password(PW)},
        {"email": "boss2@fidclic.com", "role": "super_admin", "first_name": "Mujtaba"},
        {"email": "sup@fidclic.com", "role": "fidclic_team", "platform_role": "sup", "first_name": "Sam", "hashed_password": auth.hash_password(PW)},
        {"email": "own@shop.fr", "role": "business_owner", "tenant_id": "s"},
    ])
    db.platform_roles.insert_one({"id": "sup", "name": "Support", "perms": {"support": {"view": True, "edit": True},
                                                                          "equipe": {"view": True, "edit": False}}})
    db.tenants.insert_one({"id": "s", "slug": "s", "name": "Shop", "is_active": True, "plan": "vip"})

    def login(email, role):
        """A real session (sid in the token), like a sign-in."""
        user = db.users.find_one({"email": email})
        sid = SP.open_session(user, None) if hasattr(SP, "open_session") else None
        claims = {"sub": email, "role": role}
        if sid:
            claims["sid"] = sid
        return {"Authorization": "Bearer " + auth.create_access_token(claims)}, sid

    BOSS, boss_sid = login("boss@fidclic.com", "super_admin")
    SUP, _ = login("sup@fidclic.com", "fidclic_team")
    OWN = {"Authorization": "Bearer " + auth.create_access_token({"sub": "own@shop.fr", "role": "business_owner", "tenant_id": "s"})}

    # ------------------------------------------------------------------ who
    print("Qui")
    check("a business owner: not this page (403)", http("GET", "/api/admin/me", headers=OWN).status_code == 403)
    check("no token: 401/403", http("GET", "/api/admin/me").status_code in (401, 403))
    r = http("GET", "/api/admin/me", headers=SUP)
    check("any team member reads their own (no « Paramètres » right needed)", r.status_code == 200, r.text[:200])

    # ------------------------------------------------------------------ profile
    print("\nProfil")
    me = http("GET", "/api/admin/me", headers=BOSS).json()
    check("email, names, role, password set, no 2FA yet", me["profile"]["email"] == "boss@fidclic.com"
          and me["profile"]["first_name"] == "Akshansh" and me["security"]["has_password"] is True and me["security"]["totp"] is False, me)
    r = http("PUT", "/api/admin/me/profile", headers=BOSS, json={"first_name": "  Akshansh ", "last_name": "Shukla", "phone": "06 12 34 56 78"})
    check("names trimmed, phone as the forms write it", r.status_code == 200 and r.json()["profile"]["last_name"] == "Shukla"
          and r.json()["profile"]["phone"] == "0612345678", r.text[:200])
    check("…journaled", db.audit_logs.find_one({"action": "platform.profile_update", "actor": "boss@fidclic.com"}))
    for body, label in [({"phone": "06#12"}, "a phone with letters/symbols"), ({"first_name": "x" * 81}, "a name over 80 characters"),
                        ({"email": "other@fidclic.com"}, "changing one's e-mail here"), ({"role": "super_admin"}, "changing one's role"),
                        ({"photo": "data:text/html;base64,PHNjcmlwdD4="}, "a photo that is not an image"),
                        ({"photo": "https://evil.example/x.png"}, "a photo from another site")]:
        code = http("PUT", "/api/admin/me/profile", headers=SUP, json=body).status_code
        check(f"{label} → refused", code in (400, 422), code)
    check("…the role did not move", db.users.find_one({"email": "sup@fidclic.com"})["role"] == "fidclic_team")
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 5000).decode()
    r = http("PUT", "/api/admin/me/profile", headers=SUP, json={"photo": f"data:image/png;base64,{png}"})
    check("a photo (image) is kept as a FidClic link", r.status_code == 200 and (r.json()["profile"]["photo"] or "").startswith("/api/media/"), r.text[:200])
    big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024 + 10)).decode()
    check("a photo over 2 MB → refused (413)", http("PUT", "/api/admin/me/profile", headers=SUP,
                                                   json={"photo": f"data:image/png;base64,{big}"}).status_code == 413)
    r = http("PUT", "/api/admin/me/profile", headers=SUP, json={"photo": None})
    check("removing the photo", r.status_code == 200 and r.json()["profile"]["photo"] is None)

    # ------------------------------------------------------------------ password + 2FA + sessions
    print("\nMot de passe, 2FA, sessions")
    r = http("POST", "/api/security/password", headers=SUP, json={"current": "wrong", "new": "Another-Strong-Pass-2026!"})
    check("a team member: wrong current password → 400", r.status_code == 400, r.status_code)
    r = http("POST", "/api/security/password", headers=SUP, json={"current": PW, "new": "short"})
    check("…a weak new one → refused", r.status_code in (400, 422), r.status_code)
    r = http("POST", "/api/security/password", headers=SUP, json={"current": PW, "new": "Another-Strong-Pass-2026!"})
    check("…the right one → changed", r.status_code == 200, r.text[:200])
    check("…the new password works", auth.verify_password("Another-Strong-Pass-2026!", db.users.find_one({"email": "sup@fidclic.com"})["hashed_password"]))
    r = http("POST", "/api/security/2fa/setup", headers=BOSS)
    check("2FA setup for the super admin: a secret + an otpauth link", r.status_code == 200 and r.json()["uri"].startswith("otpauth://"), r.text[:200])
    code = SP.totp(r.json()["secret"])
    r = http("POST", "/api/security/2fa/enable", headers=BOSS, json={"code": code})
    check("…the code enables it, with 10 backup codes", r.status_code == 200 and len(r.json()["backup_codes"]) == 10, r.text[:200])
    check("…and sign-in now asks for it", http("GET", "/api/admin/me", headers=BOSS).json()["security"]["totp"] is True)
    r = http("POST", "/api/auth/login", json={"email": "boss@fidclic.com", "password": PW})
    check("…a sign-in with the password alone gets the 2FA challenge, not a session",
          r.status_code == 200 and not r.json().get("access_token") and (r.json().get("requires_2fa") or r.json().get("two_factor") or r.json().get("challenge")), r.text[:200])
    # sessions
    db.user_sessions.insert_many([{"sid": "other-1", "email": "boss@fidclic.com", "revoked_at": None, "last_seen": dt.datetime.now(UTC),
                                   "created_at": dt.datetime.now(UTC), "device": "iPhone", "city": "Tours", "country": "France"},
                                  {"sid": "other-2", "email": "boss@fidclic.com", "revoked_at": None, "last_seen": dt.datetime.now(UTC),
                                   "created_at": dt.datetime.now(UTC), "device": "Mac", "city": "Paris", "country": "France"}])
    ses = http("GET", "/api/admin/me", headers=BOSS).json()["sessions"]
    check("my sessions are listed with device and place", {"other-1", "other-2"} <= {s["sid"] for s in ses}
          and any(s["place"] == "Tours, France" for s in ses), ses)
    check("…never someone else's", all(s["sid"] in {"other-1", "other-2", boss_sid} for s in ses))
    r = http("DELETE", "/api/security/sessions/other-1", headers=BOSS)
    check("one device signed out", r.status_code == 200 and db.user_sessions.find_one({"sid": "other-1"})["revoked_at"])
    check("…another person's session cannot be ended (404)", http("DELETE", "/api/security/sessions/other-2", headers=SUP).status_code == 404)
    r = http("POST", "/api/security/sessions/revoke-others", headers=BOSS)
    check("« Déconnecter les autres »", r.status_code == 200 and db.user_sessions.find_one({"sid": "other-2"})["revoked_at"], r.text[:200])

    # ------------------------------------------------------------------ alerts
    print("\nMes alertes")
    a = {x["key"]: x for x in http("GET", "/api/admin/me", headers=BOSS).json()["alerts"]}
    check("the super admin sees every alert type", set(a) == {"signup", "support", "security", "ai", "impaye", "equipe", "sante"}, list(a))
    check("defaults keep today: FidClic IA and platform health by e-mail, the rest in the bell",
          a["ai"]["value"] == "email" and a["sante"]["value"] == "email"
          and all(a[k]["value"] == "bell" for k in ("signup", "support", "security", "impaye", "equipe")), a)
    s = {x["key"] for x in http("GET", "/api/admin/me", headers=SUP).json()["alerts"]}
    check("a support member sees only what their role opens (support, team tasks)", s == {"support", "equipe"}, s)
    for body, label in [({"nope": "email"}, "an unknown type"), ({"support": "sms"}, "a channel that is not email/bell")]:
        check(f"{label} → refused", http("PUT", "/api/admin/me/alerts", headers=SUP, json=body).status_code in (400, 422))
    check("a type the role does not open → refused", http("PUT", "/api/admin/me/alerts", headers=SUP, json={"ai": "email"}).status_code == 400)
    r = http("PUT", "/api/admin/me/alerts", headers=SUP, json={"support": "email", "equipe": "email"})
    check("saved", r.status_code == 200 and {x["key"]: x["value"] for x in r.json()["alerts"]} == {"support": "email", "equipe": "email"}, r.text[:200])
    http("PUT", "/api/admin/me/alerts", headers=BOSS, json={"signup": "email", "security": "email", "impaye": "email", "ai": "bell"})

    # who receives what
    mails.clear()
    TA.notify("ai", "Plafond IA atteint", "Le plafond du jour est atteint.", "/admin/ai/couts")
    check("FidClic IA: the super admin who kept « email » gets it, not the one who chose the bell",
          [m[0] for m in mails] == ["boss2@fidclic.com"], mails)
    mails.clear()
    from features import platform_security as PS
    PS._alert("locked", "sup@fidclic.com", "Compte bloqué 15 min après 5 mots de passe erronés.", None)
    check("security: e-mailed to the super admin who asked; the bell row is written too",
          [m[0] for m in mails] == ["boss@fidclic.com"] and db.platform_alerts.find_one({"kind": "locked"}), mails)
    mails.clear()
    from services import signup_emails as SE
    SE.send_signup_emails({"id": "s", "name": "Nouveau Café"}, {"email": "new@cafe.fr", "first_name": "N"})
    got = sorted(m[0] for m in mails)
    check("new business: the FidClic inbox as before + the super admin who asked (+ the welcome mail)",
          "fidclic37@gmail.com" in got and "boss@fidclic.com" in got and "new@cafe.fr" in got and "boss2@fidclic.com" not in got, got)
    mails.clear()
    from features import billing as BI
    BI._payment_failed({"id": "s", "name": "Shop"})
    check("impayé: the tenant is past due", db.tenants.find_one({"id": "s"})["subscription_status"] == "past_due")
    check("…the super admin who asked is e-mailed, and the bell row is written",
          [m[0] for m in mails] == ["boss@fidclic.com"] and db.platform_alerts.find_one({"kind": "impaye", "tenant_id": "s"}), mails)
    mails.clear()
    from features import support_center as SC
    SC._notify_team_by_email({"id": "t1", "subject": "Ma carte ne marche pas", "tenant_id": "s"}, "Bonjour…")
    check("support: the support member who asked is e-mailed; the super admin (bell) is not",
          [m[0] for m in mails] == ["sup@fidclic.com"], mails)
    mails.clear()
    from features import team_tasks as TT
    TT._alert(["sup@fidclic.com", "boss@fidclic.com"], "assigned", {"id": "task1"}, "Nouvelle tâche : appeler Royal Trim")
    check("team tasks: only the person concerned, and only if they asked (sup: email, boss: bell)",
          [m[0] for m in mails] == ["sup@fidclic.com"], mails)
    db.users.update_one({"email": "sup@fidclic.com"}, {"$set": {"active": False}})
    mails.clear()
    SC._notify_team_by_email({"id": "t2", "subject": "x", "tenant_id": "s"}, "y")
    check("a deactivated member gets nothing", mails == [], mails)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
