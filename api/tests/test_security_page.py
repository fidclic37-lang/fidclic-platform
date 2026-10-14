"""
Paramètres › Sécurité — sessions that can be ended, TOTP 2FA at login,
password change, who may reset whose password, what each role sees, and the
30-day account deletion.

Run: cd api && /usr/local/bin/python3 tests/test_security_page.py
"""
import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    import auth
    from fastapi import HTTPException, Response
    from models import TokenData
    from features import security_page as SEC
    from features import team_access as T
    from features import store_scope as S

    db = server.db
    for m in (SEC, T, S):
        m.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class Req:
        def __init__(self, ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36",
                     city="Tours", cc="FR", store=None):
            self.headers = {"user-agent": ua, "x-vercel-ip-city": city, "x-vercel-ip-country": cc,
                            **({S.HEADER: store} if store else {})}
            self.query_params = {}
            self.client = None
            self.cookies = {}

    def who(token):
        """What auth makes of a token — the live check included."""
        class R:
            cookies = {}
            headers = {"authorization": f"Bearer {token}"}
            url = type("U", (), {"path": "/x"})()
        return asyncio.get_event_loop().run_until_complete(auth.get_current_user_data(R()))

    def refused(fn, code=None):
        try:
            fn(); return False
        except HTTPException as e:
            return code is None or e.status_code == code

    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café", "branches": [
        {"id": "tours", "name": "Tours"}, {"id": "blois", "name": "Blois"}]})
    pw = auth.hash_password("Corner!Secret-2026")
    db.users.insert_many([
        {"id": "u1", "email": "owner@c.fr", "role": "business_owner", "tenant_id": "t1", "hashed_password": pw, "first_name": "Meriem"},
        {"id": "u2", "email": "ali@c.fr", "role": "administrateur", "tenant_id": "t1", "branch_ids": ["tours", "blois"], "active": True, "hashed_password": pw},
        {"id": "u3", "email": "sara@c.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["blois"], "active": True, "hashed_password": pw},
        {"id": "u4", "email": "emp@c.fr", "role": "staff", "tenant_id": "t1", "branch_ids": ["blois"], "active": True, "hashed_password": pw},
        {"id": "u5", "email": "emp2@c.fr", "role": "staff", "tenant_id": "t1", "branch_ids": ["tours"], "active": True, "hashed_password": pw},
    ])

    def login(email, request=None):
        return server.login(server.LoginRequest(email=email, password="Corner!Secret-2026"), Response(), request or Req())

    print("\nTOTP")
    secret = SEC.new_secret()
    now = 1_790_000_000
    check("today's code is accepted, a wrong one is not",
          SEC.totp_ok(secret, SEC.totp(secret, now), now) and not SEC.totp_ok(secret, "000000", now + 999))
    check("RFC 6238 test vector", SEC.totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59, digits=6) == "287082")

    print("\nSessions")
    s1 = login("owner@c.fr")
    s2 = login("owner@c.fr", Req(ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile/15E148 Safari/604.1", city="Paris"))
    t1 = who(s1["access_token"])
    ov = SEC.overview(request=Req(), token_data=t1)
    check("each login is a device, with browser, OS and city",
          {(x["device"], x["browser"], x["os"]) for x in ov["sessions"]} == {("Mac", "Chrome", "macOS"), ("iPhone", "Safari", "iOS")}
          and any(x["place"] == "Paris, France" for x in ov["sessions"]))
    check("this device is marked current", [x["current"] for x in ov["sessions"]].count(True) == 1)
    other = next(x["sid"] for x in ov["sessions"] if not x["current"])
    SEC.end_session(other, request=Req(), token_data=t1)
    check("« Déconnecter » ends that device at once", refused(lambda: who(s2["access_token"]), 401))
    check("… not this one", who(s1["access_token"]).email == "owner@c.fr")
    check("this device cannot end itself here", refused(lambda: SEC.end_session(t1.sid, token_data=t1), 400))
    s3 = login("owner@c.fr"); login("owner@c.fr")
    check("« Tout déconnecter » closes every other device", SEC.end_others(token_data=t1)["closed"] == 2
          and refused(lambda: who(s3["access_token"]), 401))

    print("\nPassword")
    check("the current password is required", refused(lambda: SEC.change_password(SEC.PasswordIn(current="nope", new="Nouveau!Pass-2026"), token_data=t1), 400))
    check("the policy applies", refused(lambda: SEC.change_password(SEC.PasswordIn(current="Corner!Secret-2026", new="short"), token_data=t1), 422))
    s4 = login("owner@c.fr")
    SEC.change_password(SEC.PasswordIn(current="Corner!Secret-2026", new="Nouveau!Pass-2026"), token_data=t1)
    check("changed; other devices must sign in again", refused(lambda: who(s4["access_token"]), 401)
          and auth.verify_password("Nouveau!Pass-2026", db.users.find_one({"email": "owner@c.fr"})["hashed_password"]))
    db.users.update_one({"email": "owner@c.fr"}, {"$set": {"hashed_password": pw}})

    print("\n2FA")
    setup = SEC.totp_setup(token_data=t1)
    check("an otpauth link for the phone app", setup["uri"].startswith("otpauth://totp/FidClic") and "issuer=FidClic" in setup["uri"])
    check("a wrong code does not switch it on", refused(lambda: SEC.totp_enable(SEC.CodeIn(code="123456"), token_data=t1), 400))
    res = SEC.totp_enable(SEC.CodeIn(code=SEC.totp(setup["secret"])), token_data=t1)
    check("the right code switches it on, with 10 backup codes shown once", res["enabled"] and len(res["backup_codes"]) == 10)
    step = login("owner@c.fr")
    check("the next login asks for the code, no session yet", step.get("requires_2fa") and "access_token" not in step)
    check("a challenge is not a login token", refused(lambda: who(step["challenge"]), 401))
    check("a wrong code is refused",
          refused(lambda: server.login_2fa(server.TwoFactorLogin(challenge=step["challenge"], code="000000"), Response(), Req()), 400))
    done = server.login_2fa(server.TwoFactorLogin(challenge=step["challenge"], code=SEC.totp(setup["secret"])), Response(), Req())
    check("the right code opens the session", who(done["access_token"]).email == "owner@c.fr")
    step = login("owner@c.fr")
    done = server.login_2fa(server.TwoFactorLogin(challenge=step["challenge"], code=res["backup_codes"][0]), Response(), Req())
    check("a backup code works once", who(done["access_token"]).email == "owner@c.fr"
          and refused(lambda: server.login_2fa(server.TwoFactorLogin(challenge=login("owner@c.fr")["challenge"],
                                                                     code=res["backup_codes"][0]), Response(), Req()), 400))
    SEC.totp_disable(SEC.DisableIn(password="Corner!Secret-2026", code=SEC.totp(setup["secret"])), token_data=t1)
    check("switched off with password and code", "access_token" in login("owner@c.fr"))

    print("\nWho sees whom, who resets whose password")
    sara = who(login("sara@c.fr")["access_token"])
    ali = who(login("ali@c.fr")["access_token"])
    team_sara = {m["email"]: m for m in SEC.overview(request=Req(), token_data=sara)["team"]}
    check("a manager sees itself and its staff only", set(team_sara) == {"sara@c.fr", "emp@c.fr"})
    check("… and may reset its staff's password, nobody else's",
          team_sara["emp@c.fr"]["can_reset_password"] and not team_sara["sara@c.fr"]["can_reset_password"])
    check("… which the team endpoint enforces",
          refused(lambda: T.new_password("u5", token=sara), 403) and T.new_password("u4", token=sara)["credentials"]["email"] == "emp@c.fr")
    team_ali = {m["email"] for m in SEC.overview(request=Req(store="tours"), token_data=ali)["team"]}
    check("an administrateur, on Tours in the menu, sees Tours' team", "emp2@c.fr" in team_ali and "emp@c.fr" not in team_ali)
    act_sara = SEC.overview(request=Req(), token_data=sara)["activity"]
    check("a manager's activity is its own and its staff's", act_sara and all(a["by"] in ("sara", "emp", "sara@c.fr", "emp@c.fr") for a in act_sara))
    owner = who(login("owner@c.fr")["access_token"])
    check("the owner's activity covers everyone, with device and city",
          any(a["label"] == "Connexion réussie" and "Chrome" in a["where"] and "Tours" in a["where"]
              for a in SEC.overview(request=Req(), token_data=owner)["activity"]))

    print("\nDeleting the account")
    check("SUPPRIMER must be typed", refused(lambda: SEC.delete_account(SEC.DeleteIn(password="Corner!Secret-2026", confirm="oui"), token_data=sara), 400))
    SEC.delete_account(SEC.DeleteIn(password="Corner!Secret-2026", confirm="SUPPRIMER"), token_data=sara)
    check("a manager deletes only its own login", db.users.find_one({"email": "sara@c.fr"}) is None
          and db.tenants.find_one({"id": "t1"}) is not None)
    ali_token = login("ali@c.fr")["access_token"]
    r = SEC.delete_account(SEC.DeleteIn(password="Corner!Secret-2026", confirm="SUPPRIMER"), token_data=owner)
    check("the owner: business closed, deleted in 30 days", r["deleted"] == "scheduled")
    check("everyone else is signed out and kept out", refused(lambda: who(ali_token), 401) and refused(lambda: login("ali@c.fr"), 403))
    check("the owner can still sign in to change its mind", "access_token" in login("owner@c.fr"))
    SEC.restore_account(token_data=owner)
    check("cancelled: the team signs in again", "access_token" in login("ali@c.fr"))
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Ana"})
    db.fidclic_invoices.insert_one({"id": "i1", "tenant_id": "t1", "number": "FAC-2026-0001"})
    SEC.delete_account(SEC.DeleteIn(password="Corner!Secret-2026", confirm="SUPPRIMER"), token_data=owner)
    check("nothing is removed before 30 days", SEC.purge_due()["tenants"] == 0 and db.customers.count_documents({"tenant_id": "t1"}) == 1)
    res = SEC.purge_due(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=31))
    check("after 30 days: the business, its clients and its accounts are gone",
          res["tenants"] == 1 and db.tenants.find_one({"id": "t1"}) is None
          and db.customers.count_documents({"tenant_id": "t1"}) == 0 and db.users.count_documents({"tenant_id": "t1"}) == 0)
    check("FidClic's invoices stay (legal retention)", db.fidclic_invoices.count_documents({"tenant_id": "t1"}) == 1)

    # The session slides (user, 2026-10-14: « ye platform login hai roz jo karna
    # padega user ko »). Opening the app starts the month again; what ends a
    # session is still « Déconnecter », not the clock.
    import jwt as _jwt
    db.users.insert_one({"id": "u9", "email": "caisse@c.fr", "role": "business_owner",
                         "tenant_id": "t1", "hashed_password": pw, "first_name": "Till"})
    sess = login("caisse@c.fr")
    tok = sess["access_token"]
    claims = _jwt.decode(tok, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    check("a month, not a day", 29 * 24 * 3600 < claims["exp"] - dt.datetime.now(dt.timezone.utc).timestamp())

    own = TokenData(email="caisse@c.fr", role="business_owner", tenant_id="t1", sid=claims["sid"])
    out = server.get_me(own, Response())
    fresh = out.get("access_token")
    check("opening the app hands back a token", bool(fresh))
    if fresh:
        c2 = _jwt.decode(fresh, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        check("…for another month, same session", c2["sid"] == claims["sid"] and c2["sub"] == "caisse@c.fr")
        check("a slid session is still a live one", SEC.session_ok("caisse@c.fr", claims["sid"]) is True)
        SEC.revoke({"sid": claims["sid"]})
        check("…and « Déconnecter » ends it, slid or not",
              SEC.session_ok("caisse@c.fr", claims["sid"]) is False)

    # « Accéder au compte »: the super admin's view of someone else's account
    # keeps its own short life — sliding it here would make it permanent.
    view = TokenData(email="caisse@c.fr", role="business_owner", tenant_id="t1",
                     sid=claims["sid"], view_by="admin@fidclic.com")
    out2 = server.get_me(view, Response())
    check("a « Accéder au compte » token is never slid", "access_token" not in out2)

    # « Cet appareil est la caisse » (user, 2026-10-14): a till is left on a
    # counter, it must not be mistaken for someone's phone in the list, and it
    # must not be sent back to a login screen after a seasonal closure.
    caisse_tok = TokenData(email="caisse@c.fr", role="business_owner", tenant_id="t1", sid=claims["sid"])
    db.tenants.update_one({"id": "t1"}, {"$set": {"id": "t1", "branches": [    # the deletion test above emptied it
        {"id": "tours", "name": "Tours"}, {"id": "blois", "name": "Blois"}]}}, upsert=True)
    db.user_sessions.update_one({"sid": claims["sid"]}, {"$set": {"revoked_at": None}})   # the revoke test above
    SEC.mark_caisse(SEC.CaisseIn(store_id="tours"), Req(), token_data=caisse_tok)
    row = next(x for x in SEC.overview(request=Req(), token_data=caisse_tok)["sessions"]
               if x["sid"] == claims["sid"])
    check("the list says « Caisse », and where it sits",
          row["caisse"] and row["caisse"]["store_id"] == "tours")
    check("a till is a till", SEC.is_caisse(claims["sid"]) is True)

    slid = server.get_me(caisse_tok, Response()).get("access_token")
    c3 = _jwt.decode(slid, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    left = c3["exp"] - dt.datetime.now(dt.timezone.utc).timestamp()
    check("a till's session is six months, not one", left > 170 * 24 * 3600)

    try:
        SEC.mark_caisse(SEC.CaisseIn(store_id="nowhere"), Req(), token_data=caisse_tok)
        check("an establishment that does not exist is refused", False)
    except HTTPException as e:
        check("an establishment that does not exist is refused", e.status_code == 400)

    SEC.revoke({"sid": claims["sid"]})
    check("« Déconnecter » ends a till like any other device",
          SEC.session_ok("caisse@c.fr", claims["sid"]) is False)
    db.user_sessions.update_one({"sid": claims["sid"]}, {"$set": {"revoked_at": None}})
    SEC.unmark_caisse(Req(), token_data=caisse_tok)
    check("…and it can go back to being an ordinary device", SEC.is_caisse(claims["sid"]) is False)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
