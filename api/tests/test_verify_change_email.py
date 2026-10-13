"""
« Modifier l'adresse e-mail » on the sign-up code page (QA BUG-001, 2026-10-11):
an owner who typed « …@gmial.com » waited for a code sent elsewhere and could
only log out. While the account is being verified, the address can be
corrected; the code then goes to the new one.

Run: cd api && /usr/local/bin/python3 tests/test_verify_change_email.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-verify-email")
os.environ.setdefault("DISABLE_SEED", "1")

import services.email_check as EC  # noqa: E402

EC.domain_receives_mail = lambda d: None          # offline: DNS « unreachable » → accepted
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import httpx
    from services import mailer, sms

    db = server.db
    sent = []
    mailer.ready = lambda: True
    mailer.send = lambda to, subject, html, text=None, **k: sent.append((to, subject)) or {"sent": True}
    sms.is_configured = lambda: False

    def http(method, url, token, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "chez-ahmed", "name": "Chez Ahmed", "onboarding_status": "verify",
                           "is_active": False, "phone": "0612345678"})
    db.users.insert_one({"email": "ahmed@gmial.com", "role": "business_owner", "tenant_id": "t1", "active": True,
                         "first_name": "Ahmed"})
    db.users.insert_one({"email": "deja@pris.fr", "role": "business_owner", "tenant_id": "t9", "active": True})
    # a real sign-up session (it carries its session id, as the browser's does)
    from fastapi import Response
    old_token = server._issue_session(Response(), db.users.find_one({"email": "ahmed@gmial.com"}))["access_token"]

    print("\nThe code went to a mistyped address")
    r = http("POST", "/api/onboarding/verify/send", old_token, json={"channel": "email"})
    check(f"sent to the typo ({sent[-1][0] if sent else None})", r.status_code == 200 and sent[-1][0] == "ahmed@gmial.com")

    print("\n« Modifier l'adresse e-mail »")
    r = http("POST", "/api/onboarding/verify/email", old_token, json={"email": "ahmed@gmial.com"})
    check(f"the same address: told so ({r.json().get('detail')})", r.status_code == 400)
    r = http("POST", "/api/onboarding/verify/email", old_token, json={"email": "ahmed@hotmial.fr"})
    check(f"another typo: the fix is offered ({r.json().get('detail')})", r.status_code == 400 and "hotmail.fr" in r.json()["detail"])
    r = http("POST", "/api/onboarding/verify/email", old_token, json={"email": "Deja@pris.fr"})
    check(f"another account's address: refused ({r.status_code})", r.status_code == 409)
    r = http("POST", "/api/onboarding/verify/email", old_token, json={"email": "  Ahmed@Gmail.com "})
    check(f"the right address: accepted ({r.status_code})", r.status_code == 200 and r.json().get("access_token"))
    new_token = r.json()["access_token"]
    check(f"…shown masked ({r.json().get('email')})", r.json().get("email") == "ah•••@gmail.com")
    u = db.users.find_one({"tenant_id": "t1"})
    check("the account's login is the new address, the old one remembered",
          u["email"] == "ahmed@gmail.com" and u.get("email_changed_from") == "ahmed@gmial.com")
    check("the code sent to the old address can no longer be used",
          db.signup_codes.count_documents({"email": "ahmed@gmial.com", "used": False}) == 0)
    check(f"the old session no longer opens the account ({http('GET', '/api/onboarding/verify', old_token).status_code})",
          http("GET", "/api/onboarding/verify", old_token).status_code in (401, 403, 404))
    st = http("GET", "/api/onboarding/verify", new_token).json()
    check(f"the new one does ({st.get('email')})", st.get("email") == "ah•••@gmail.com")

    print("\nThe code now goes to the corrected address")
    r = http("POST", "/api/onboarding/verify/send", new_token, json={"channel": "email"})
    check(f"sent to ahmed@gmail.com, at once (no wait inherited) ({r.status_code})",
          r.status_code == 200 and sent[-1][0] == "ahmed@gmail.com")
    code = re.match(r"(\d{6})", sent[-1][1]).group(1)
    r = http("POST", "/api/onboarding/verify/check", new_token, json={"code": code})
    check(f"and it verifies the account ({r.json()})", r.status_code == 200 and r.json().get("onboarding_status") == "company")
    check("the new address is the verified one", db.users.find_one({"email": "ahmed@gmail.com"}).get("email_verified_at"))

    print("\nOnly while verifying, and not endlessly")
    r = http("POST", "/api/onboarding/verify/email", new_token, json={"email": "ahmed2@gmail.com"})
    check(f"a verified account changes its address in Paramètres, not here ({r.status_code})", r.status_code == 409)
    db.tenants.update_one({"id": "t1"}, {"$set": {"onboarding_status": "verify"}})
    tok, codes = new_token, []
    for i in range(3):
        r = http("POST", "/api/onboarding/verify/email", tok, json={"email": f"ahmed.{i}@gmail.com"})
        codes.append(r.status_code)
        tok = r.json().get("access_token", tok)
    check(f"3 changes an hour at most ({codes})", codes[:2] == [200, 200] and codes[2] == 429)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
