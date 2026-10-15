"""
Tests — self-serve onboarding (company step, plan step, hidden drafts),
30-day Pro AI trial + day-29 reminder, Google / Apple sign-in account rules.
Run:  cd api && python3 tests/test_onboarding_oauth.py

Boots the REAL server.py against mongomock (pymongo is patched before the
import), so /api/auth/register, /api/onboarding/company and the cron hook
run exactly the code that ships — no re-implementation in the test.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import mongomock

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("BREVO_API_KEY", "test-key")
os.environ.pop("MONGODB_URI", None)

_patch = mongomock.patch(servers=(("localhost", 27017),))
_patch.start()
import server as S                      # noqa: E402 — must come after the patch
import features.onboarding as OB        # noqa: E402
import features.oauth as OA             # noqa: E402
from services import mailer             # noqa: E402
from fastapi import Response            # noqa: E402
import services.email_check as EC       # noqa: E402
import features.signup_verify as SV     # noqa: E402
SV.init(S.db)
# No network in tests: the domain check answers « unknown » (fail-open), and
# the older flows run without the code step (test_signup_verify turns it on).
EC.domain_receives_mail = lambda d: None
_real_required = SV.verification_required
SV.verification_required = lambda: False

PASS, FAIL = [], []
SENT = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}{('  → ' + str(extra)) if extra and not cond else ''}")


def expect_status(name, code, fn):
    try:
        fn()
        check(name, False, f"no error raised (expected {code})")
    except Exception as e:
        check(name, getattr(e, "status_code", None) == code, e)


def fake_post(payload, key):
    SENT.append(payload)
    return {"messageId": f"test-{len(SENT)}"}


def tok(email, role="business_owner", tenant_id=None):
    return SimpleNamespace(email=email, role=role, tenant_id=tenant_id)


def reset():
    S.db.users.delete_many({})
    S.db.tenants.delete_many({})
    S.db.audit_log.delete_many({}) if "audit_log" in S.db.list_collection_names() else None
    SENT.clear()
    mailer._post = fake_post


STEP1 = {"first_name": "Marie", "last_name": "Dupont", "email": "Marie@Cafe.fr",
         "phone": "06 12 34 56 78", "password": "Cafe-Lumiere2026!", "accepted_terms": True}
from services import addresses as ADR   # noqa: E402
TOURS = {"kind": "address", "country": "FR", "street": "12 rue des Halles", "postcode": "37000",
         "city": "Tours", "lat": 47.393, "lng": 0.684}
STEP2 = {"legal_name": "SARL Café Lumière", "name": "Café Lumière", "sector": "cafe",
         "activity": "Café / brunch", "siret": "123 456 789 00012",
         "address_token": ADR.sign(TOURS)}


def test_step1():
    print("\nStep 1 — /api/auth/register (personal account)")
    reset()
    expect_status("missing CGU/DPA consent → 400", 400,
                  lambda: S.register({**STEP1, "accepted_terms": False}, Response()))
    expect_status("missing last name → 400", 400,
                  lambda: S.register({**STEP1, "last_name": ""}, Response()))
    expect_status("weak password → 422 (policy)", 422,
                  lambda: S.register({**STEP1, "password": "123456"}, Response()))
    resp = Response()
    out = S.register(dict(STEP1), resp)
    check("returns a session token (auto-login)", bool(out.get("access_token")))
    check("cookie is set on the response", "access_token=" in resp.headers.get("set-cookie", ""))
    check("onboarding_status = company (step 2 pending)", out.get("onboarding_status") == "company")
    u = S.db.users.find_one({"email": "marie@cafe.fr"})
    check("email lower-cased, names stored", u and u["first_name"] == "Marie" and u["last_name"] == "Dupont")
    check("terms_accepted_at + version stamped", u["terms_accepted_at"] is not None and u["terms_version"] == S.TERMS_VERSION)
    t = S.db.tenants.find_one({"id": u["tenant_id"]})
    check("tenant stub: no trial yet (status=onboarding)",
          t["subscription_status"] == "onboarding" and "trial_ends_at" not in t)
    check("tenant stub is a hidden draft (is_active=False)", t["is_active"] is False)
    expect_status("same email twice → 400", 400, lambda: S.register(dict(STEP1), Response()))
    return u


def test_legacy_register():
    print("\nLegacy form (business_name present) keeps working")
    reset()
    out = S.register({"email": "old@shop.fr", "password": "Old-Shop2026!!", "business_name": "Old Shop"}, Response())
    t = S.db.tenants.find_one({"id": out["tenant_id"]})
    check("legacy → onboarding done + trial started", t["onboarding_status"] == "done"
          and t["subscription_status"] == "trialing")
    check("legacy trial is 30 days", t["trial_duration_days"] == 30)


def test_step2(u):
    print("\nStep 2 — /api/onboarding/company")
    tk = tok(u["email"], tenant_id=u["tenant_id"])
    expect_status("address not picked from the list → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "address_token": None}), None, tk))
    expect_status("13-digit SIRET → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "siret": "1234567890001"}), None, tk))
    expect_status("unknown sector → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "sector": "crypto"}), None, tk))
    expect_status("plan step before the company step → 409", 409, lambda: OB.start_trial(None, tk))
    out = OB.complete_company(OB.CompanyDetails(**STEP2), None, tk)
    t = S.db.tenants.find_one({"id": u["tenant_id"]})
    check("company done → plan step next", out["onboarding_status"] == "plan" and t["onboarding_status"] == "plan")
    check("still a hidden draft, no trial yet", t["is_active"] is False and "trial_ends_at" not in t
          and out["trial"] is None)
    check("the card starts with the sector's reward (a café: « Un café offert »)",
          (S.db.card_templates.find_one({"tenant_id": u["tenant_id"]}) or {}).get("reward_description") == "Un café offert")
    me = S.get_me(tok(u["email"], tenant_id=u["tenant_id"]))
    check("/me says plan (UI parks the owner on /onboarding/formule)", me["onboarding_status"] == "plan")
    st = OB.onboarding_status(tk)
    check("status exposes the trial plan + days", st["trial_plan"] == "vip" and st["trial_days"] == 30)
    S.db.tenants.update_one({"id": u["tenant_id"]}, {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(days=3)}})
    SENT.clear()
    out = OB.start_trial(None, tk)
    t = S.db.tenants.find_one({"id": u["tenant_id"]})
    admin_mail = next((m for m in SENT if m["to"][0]["email"] == "fidclic37@gmail.com"), None)
    welcome = next((m for m in SENT if m["to"][0]["email"] == "marie@cafe.fr"), None)
    check("FidClic is told: « Nouveau commerce inscrit » with the details",
          admin_mail and "Café Lumière" in admin_mail["subject"] and "marie@cafe.fr" in admin_mail["htmlContent"]
          and "/admin/commerces/" in admin_mail["htmlContent"])
    check("the owner gets the French welcome, with the trial, the steps, their link and how to reach us",
          welcome and "Bienvenue dans la famille FidClic" in welcome["htmlContent"]
          and "30 jours de Pro AI" in welcome["htmlContent"] and "/join/cafe-lumiere" in welcome["htmlContent"]
          and "contact@fidclic.com" in welcome["htmlContent"] and welcome.get("replyTo", {}).get("email") == "contact@fidclic.com")
    check("the owner's name is escaped, never raw HTML", "<script" not in welcome["htmlContent"])
    check("plan step → onboarding done, business live", out["onboarding_status"] == "done"
          and t["onboarding_status"] == "done" and t["is_active"] is True)
    check("trial runs on Pro AI (vip)", t["plan"] == "vip" and out["plan"] == "vip")
    check("trial started NOW for 30 days", t["subscription_status"] == "trialing"
          and t["trial_duration_days"] == 30 and out["trial"]["days_left"] in (29, 30))
    check("created_at = the day it went live", (datetime.now(timezone.utc) - (t["created_at"] if t["created_at"].tzinfo else t["created_at"].replace(tzinfo=timezone.utc))).total_seconds() < 60)
    ends0 = t["trial_ends_at"]
    sent_before = len(SENT)
    OB.start_trial(None, tk)
    check("a second click sends no second welcome", len(SENT) == sent_before)
    check("start-trial twice does NOT restart the trial", S.db.tenants.find_one({"id": u["tenant_id"]})["trial_ends_at"] == ends0)
    check("slug regenerated from the shop name", t["slug"] == "cafe-lumiere")
    check("legal identity stored (SIRET digits only, SIREN derived)",
          t["legal_name"] == "SARL Café Lumière" and t["siret"] == "12345678900012" and t["siren"] == "123456789")
    check("address assembled", t["address"] == "12 rue des Halles, 37000 Tours" and t["city"] == "Tours")
    ends = t["trial_ends_at"]
    OB.complete_company(OB.CompanyDetails(**{**STEP2, "activity": "Brunch"}), None, tk)
    t2 = S.db.tenants.find_one({"id": u["tenant_id"]})
    check("re-submitting does NOT restart the trial", t2["trial_ends_at"] == ends and t2["activity"] == "Brunch")
    me = S.get_me(tok(u["email"], tenant_id=u["tenant_id"]))
    check("/me exposes onboarding_status=done + names", me["onboarding_status"] == "done" and me["first_name"] == "Marie")


def test_reminder(u):
    print("\nDay 29 — trial reminder via daily cron")
    SENT.clear()                       # the welcome e-mails of step 3 are not reminders
    tid = u["tenant_id"]
    now = datetime.now(timezone.utc)
    # Day 10 of 30: nothing should go out.
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": now + timedelta(days=18)},
                                           "$unset": {"trial_reminder_sent_at": ""}})
    r = OB.run_trial_reminders()
    check("day 10 → no email", r["reminders_sent"] == 0 and len(SENT) == 0)
    # Day 29: 1 day left → one email, then never again.
    # days_left is counted in *calendar days* in Paris (QA UX07), so pin the
    # end to midday tomorrow in Paris — "+30 h" landed two calendar days away
    # whenever the suite ran after 18 h Paris time.
    from zoneinfo import ZoneInfo
    _paris = ZoneInfo("Europe/Paris")
    tomorrow_noon = (now.astimezone(_paris) + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": tomorrow_noon}})
    r = OB.run_trial_reminders()
    check("day 29 → exactly one email to the owner", r["reminders_sent"] == 1 and SENT[-1]["to"][0]["email"] == "marie@cafe.fr")
    check("email is in French and links to billing", "se termine" in SENT[-1]["htmlContent"]
          and "/dashboard/parametres/abonnement" in SENT[-1]["htmlContent"])
    r = OB.run_trial_reminders()
    check("re-running the cron does NOT resend", r["reminders_sent"] == 0 and len(SENT) == 1)
    # Expired trial: reminder pointless, and the trial state says expired.
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": now - timedelta(hours=2)},
                                           "$unset": {"trial_reminder_sent_at": ""}})
    r = OB.run_trial_reminders()
    st = S._compute_trial_state(S.db.tenants.find_one({"id": tid}))
    check("expired → no email, is_expired=true", r["reminders_sent"] == 0 and st["is_expired"])


def test_oauth():
    print("\nGoogle / Apple — account rules (token verification stubbed)")
    reset()
    # New Google user → tenant stub, no terms yet, onboarding pending.
    out = OA._upsert_user("google", "g-123", "Paul@Bar.fr", "Paul", "Martin", None, Response())
    u = S.db.users.find_one({"email": "paul@bar.fr"})
    check("new OAuth user → business_owner without password", u["role"] == "business_owner" and u["hashed_password"] is None)
    check("provider recorded, is_new=true, terms NOT accepted", u["oauth"]["google"] == "g-123" and out["is_new"] and not out["terms_accepted"])
    check("onboarding pending", out["onboarding_status"] == "company")
    tk = tok("paul@bar.fr", tenant_id=u["tenant_id"])
    expect_status("step 2 without consent (OAuth user) → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**STEP2), None, tk))
    OB.complete_company(OB.CompanyDetails(**{**STEP2, "accepted_terms": True}), None, tk)
    u = S.db.users.find_one({"email": "paul@bar.fr"})
    check("consent collected at step 2 for OAuth users", u["terms_accepted_at"] is not None)
    check("OAuth stub is a hidden draft too", S.db.tenants.find_one({"id": u["tenant_id"]})["is_active"] is False)
    # Password login against an OAuth-only account is refused with a hint.
    expect_status("password login on Google-only account → 400", 400,
                  lambda: S.login(S.LoginRequest(email="paul@bar.fr", password="whatever"), Response()))
    # Existing password account + Google with same email → linked, not duplicated.
    S.register(dict(STEP1), Response())
    out = OA._upsert_user("google", "g-999", "marie@cafe.fr", None, None, None, Response())
    u = S.db.users.find_one({"email": "marie@cafe.fr"})
    check("existing account linked (is_new=false, password kept, sub stored)",
          not out["is_new"] and u["hashed_password"] and u["oauth"]["google"] == "g-999")
    check("only one user for that email", S.db.users.count_documents({"email": "marie@cafe.fr"}) == 1)
    # Config endpoint hides unset providers.
    os.environ.pop("GOOGLE_CLIENT_ID", None)
    cfg = OA.oauth_config()
    check("config: unset provider → null (button hidden)", cfg["google_client_id"] is None)
    expect_status("google login unconfigured → 503", 503,
                  lambda: OA.google_login(OA.GoogleLogin(credential="x"), None, Response()))
    os.environ["GOOGLE_CLIENT_ID"] = "cid.apps.googleusercontent.com"
    expect_status("garbage credential → 401 (never 500)", 401,
                  lambda: OA.google_login(OA.GoogleLogin(credential="not-a-jwt"), None, Response()))


def test_verified_address():
    print("\nStep 2 — the address comes from the address service, inside the chosen country")
    reset()
    out = S.register({**STEP1, "email": "addr@shop.fr"}, Response())
    tk = tok("addr@shop.fr", tenant_id=out["tenant_id"])
    base = {k: v for k, v in STEP2.items() if k != "address_token"}
    expect_status("no suggestion picked → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**base, "address": "12 rue X", "postal_code": "75000", "city": "Lyon"}), None, tk))
    forged = ADR.sign(TOURS)[:-3] + "AAA"
    expect_status("tampered token → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**base, "address_token": forged}), None, tk))
    raw, mac = ADR.sign(TOURS).split(".")
    import base64 as _b, json as _j
    edited = _j.dumps({**TOURS, "city": "Lyon"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    expect_status("city edited inside the token → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**base, "address_token":
                      _b.urlsafe_b64encode(edited).decode().rstrip("=") + "." + mac}), None, tk))
    expect_status("French address with Belgium selected → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "country": "BE"}), None, tk))
    OB.complete_company(OB.CompanyDetails(**{**STEP2, "address": "999 fake street", "city": "Paris", "postal_code": "75001"}), None, tk)
    t = S.db.tenants.find_one({"id": out["tenant_id"]})
    check("typed text ignored: the address is the verified one", t["address"] == "12 rue des Halles, 37000 Tours"
          and t["city"] == "Tours" and t["postal_code"] == "37000" and t["address_verified"] == "address")
    check("coordinates stored from the address", t["lat"] == 47.393 and t["lng"] == 0.684 and t["pin_source"] == "adresse")
    # « Adresse introuvable » : verified city, typed street
    city_be = ADR.sign({"kind": "city", "country": "BE", "street": "", "postcode": "", "city": "Bruxelles", "lat": 50.85, "lng": 4.35})
    cb = {**base, "country": "BE", "address_token": city_be}
    expect_status("city path without a street → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**cb, "address": "12", "postal_code": "1000"}), None, tk))
    expect_status("Belgian city, French-looking postcode → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**cb, "address": "Rue Neuve 15", "postal_code": "75000"}), None, tk))
    OB.complete_company(OB.CompanyDetails(**{**cb, "address": "Rue Neuve 15", "postal_code": "1000"}), None, tk)
    t = S.db.tenants.find_one({"id": out["tenant_id"]})
    check("city path: verified city + typed street + 4-digit Belgian code", t["address"] == "Rue Neuve 15, 1000 Bruxelles"
          and t["country"] == "BE" and t["address_verified"] == "city")
    # search: never a city of another country
    real_get = ADR._get
    ADR._get = lambda url, params: {"features": [
        {"properties": {"type": "city", "name": "Paris", "countrycode": "US", "state": "Texas"}, "geometry": {"coordinates": [-95.5, 33.6]}},
        {"properties": {"type": "city", "name": "Paris", "countrycode": "FR", "postcode": "75001"}, "geometry": {"coordinates": [2.35, 48.85]}},
    ]}
    try:
        res = ADR.search("Paris", "US", "city")
        check("search keeps only the selected country", [r["city"] for r in res] == ["Paris"] and res[0]["country"] == "US")
        check("each suggestion is signed and verifies", ADR.verify(res[0]["token"])["city"] == "Paris")
    finally:
        ADR._get = real_get
    check("postcode shapes", ADR.postcode_ok("FR", "37000") and not ADR.postcode_ok("FR", "3700")
          and ADR.postcode_ok("CH", "1003") and ADR.postcode_ok("MC", "98000") and not ADR.postcode_ok("MC", "75000"))


def test_signup_verify():
    print("\nStep 1 — a real e-mail, then a code by e-mail (or SMS)")
    reset()
    expect_status("malformed e-mail refused at sign-up", 400,
                  lambda: S.register({**STEP1, "email": "marie@gmail"}, Response()))
    try:
        S.register({**STEP1, "email": "marie@gmial.com"}, Response())
        check("typo refused with the fix", False)
    except Exception as e:
        check("typo refused with the fix", getattr(e, "status_code", 0) == 400 and "gmail.com" in str(e.detail))
    expect_status("throwaway address refused", 400, lambda: S.register({**STEP1, "email": "x@yopmail.com"}, Response()))
    check("live check endpoint", SV.check_email("a@b") ["ok"] is False and SV.check_email("marie@cafe.fr")["ok"] is True)

    SV.verification_required = _real_required          # Brevo key is set in this test env
    try:
        out = S.register(dict(STEP1), Response())
        check("with a channel configured, sign-up starts at « verify »", out.get("onboarding_status") == "verify")
        u = S.db.users.find_one({"email": "marie@cafe.fr"})
        tk = tok(u["email"], tenant_id=u["tenant_id"])
        expect_status("company step blocked until verified", 409,
                      lambda: OB.complete_company(OB.CompanyDetails(**STEP2), None, tk))
        st = SV.verify_state(tk)
        check("channels: e-mail on (Brevo), SMS off (no Twilio)", st["channels"] == {"email": True, "sms": False})
        expect_status("SMS not configured → 503", 503, lambda: SV.send_code(SV.SendIn(channel="sms"), tk))
        r = SV.send_code(SV.SendIn(channel="email"), tk)
        mail = SENT[-1]
        code = mail["subject"].split(" ")[0]
        check("a 6-digit code is e-mailed to the owner", r["ok"] and len(code) == 6 and code.isdigit()
              and mail["to"][0]["email"] == "marie@cafe.fr")
        check("the code is stored hashed, never in clear",
              all(code not in str(v) for v in S.db.signup_codes.find_one({"email": "marie@cafe.fr"}).values()))
        expect_status("resend within 60 s → 429", 429, lambda: SV.send_code(SV.SendIn(channel="email"), tk))
        wrong = "000000" if code != "000000" else "111111"
        expect_status("wrong code → 400", 400, lambda: SV.check_code(SV.CheckIn(code=wrong), tk))
        out = SV.check_code(SV.CheckIn(code=f" {code[:3]} {code[3:]} "), tk)
        u = S.db.users.find_one({"email": "marie@cafe.fr"})
        check("right code (spaces ignored) → company step, e-mail marked verified",
              out["onboarding_status"] == "company" and u.get("email_verified_at") is not None
              and S.db.tenants.find_one({"id": u["tenant_id"]})["onboarding_status"] == "company")
        expect_status("verifying twice → 409", 409, lambda: SV.check_code(SV.CheckIn(code=code), tk))
        OB.complete_company(OB.CompanyDetails(**STEP2), None, tk)
        check("then step 2 works as before", S.db.tenants.find_one({"id": u["tenant_id"]})["onboarding_status"] == "plan")

        # tries and expiry
        S.register({**STEP1, "email": "paul@cafe.fr"}, Response())
        u2 = S.db.users.find_one({"email": "paul@cafe.fr"}); tk2 = tok(u2["email"], tenant_id=u2["tenant_id"])
        SV.send_code(SV.SendIn(channel="email"), tk2)
        good = SENT[-1]["subject"].split(" ")[0]
        bad = "000000" if good != "000000" else "111111"
        for _ in range(5):
            try:
                SV.check_code(SV.CheckIn(code=bad), tk2)
            except Exception:
                pass
        expect_status("after 5 wrong tries even the right code is refused", 400,
                      lambda: SV.check_code(SV.CheckIn(code=good), tk2))
        S.db.signup_codes.update_many({"email": "paul@cafe.fr"}, {"$set": {"tries": 0,
                                       "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
        expect_status("an expired code is refused", 400, lambda: SV.check_code(SV.CheckIn(code=good), tk2))
        os.environ.pop("BREVO_API_KEY", None)
        check("no e-mail and no SMS configured → nobody is stuck: sign-up skips the code",
              S.register({**STEP1, "email": "lea@cafe.fr"}, Response())["onboarding_status"] == "company")
        os.environ["BREVO_API_KEY"] = "test-key"
    finally:
        SV.verification_required = lambda: False


def test_drafts():
    print("\nHidden drafts — never in the super admin, purged after 7 days")
    reset()
    import features.admin_commerces as AC
    import features.crm as CRM
    now = datetime.now(timezone.utc)
    a = S.register({**STEP1, "email": "fresh@a.fr"}, Response())          # step 1 only, today
    b = S.register({**STEP1, "email": "old@b.fr"}, Response())            # step 2 done, 8 days ago
    OB.complete_company(OB.CompanyDetails(**{**STEP2, "name": "Old Draft"}), None, tok("old@b.fr", tenant_id=b["tenant_id"]))
    S.db.tenants.update_one({"id": b["tenant_id"]}, {"$set": {"created_at": now - timedelta(days=8)}})
    c = S.register({**STEP1, "email": "live@c.fr"}, Response())           # finished, 8 days ago
    tc = tok("live@c.fr", tenant_id=c["tenant_id"])
    OB.complete_company(OB.CompanyDetails(**{**STEP2, "name": "Live Shop"}), None, tc)
    OB.start_trial(None, tc)
    S.db.tenants.update_one({"id": c["tenant_id"]}, {"$set": {"created_at": now - timedelta(days=8)}})
    # A draft made before this change, still visible.
    S.db.tenants.insert_one({"id": "legacy-draft", "name": "Legacy draft", "slug": "legacy-draft",
                             "onboarding_status": "company", "created_at": now - timedelta(days=1)})
    listed = {t["id"] for t in S.db.tenants.find({"is_active": {"$ne": False}})}
    check("only the finished business is in admin lists", c["tenant_id"] in listed
          and a["tenant_id"] not in listed and b["tenant_id"] not in listed)
    CRM.sync_tenants()
    linked = {p.get("tenant_id") for p in S.db.crm_prospects.find({})}
    check("CRM sync skips drafts", c["tenant_id"] in linked and a["tenant_id"] not in linked and b["tenant_id"] not in linked)
    r = OB.purge_abandoned_signups()
    check("purge hides the old visible draft", r["hidden"] == 1
          and S.db.tenants.find_one({"id": "legacy-draft"})["is_active"] is False)
    check("purge deletes drafts older than 7 days, with their login", r["deleted"] == 1
          and not S.db.tenants.find_one({"id": b["tenant_id"]}) and not S.db.users.find_one({"email": "old@b.fr"}))
    check("recent draft kept (owner can resume)", S.db.tenants.find_one({"id": a["tenant_id"]}) is not None
          and S.db.users.find_one({"email": "fresh@a.fr"}) is not None)
    check("live business never touched", S.db.tenants.find_one({"id": c["tenant_id"]}) is not None)
    sd = S.db.tenants.find_one({"id": c["tenant_id"]})
    S.db.tenants.update_one({"id": c["tenant_id"]}, {"$set": {"is_active": False}})   # soft-deleted by an admin
    OB.purge_abandoned_signups()
    check("soft-deleted live business is not purged", S.db.tenants.find_one({"id": c["tenant_id"]}) is not None)
    S.db.tenants.update_one({"id": c["tenant_id"]}, {"$set": {"is_active": sd["is_active"]}})
    pp = __import__("features.plans_public", fromlist=["x"]).public_plans()
    check("public plans: trial = 30 days on Pro AI", pp["trial_days"] == 30 and pp["trial_plan"] == "vip"
          and all(p["trial_days"] == 30 for p in pp["plans"]))


if __name__ == "__main__":
    u = test_step1()
    test_step2(u)
    test_reminder(u)
    test_legacy_register()
    test_oauth()
    test_verified_address()
    test_signup_verify()
    test_drafts()
    _patch.stop()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)
