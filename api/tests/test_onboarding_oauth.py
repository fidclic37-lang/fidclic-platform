"""
Tests — self-serve onboarding (2 steps), 28-day trial + day-27 reminder,
Google / Apple sign-in account rules.
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
STEP2 = {"legal_name": "SARL Café Lumière", "name": "Café Lumière", "sector": "cafe",
         "activity": "Café / brunch", "siret": "123 456 789 00012",
         "address": "12 rue des Halles", "postal_code": "37000", "city": "Tours"}


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
    expect_status("same email twice → 400", 400, lambda: S.register(dict(STEP1), Response()))
    return u


def test_legacy_register():
    print("\nLegacy form (business_name present) keeps working")
    reset()
    out = S.register({"email": "old@shop.fr", "password": "Old-Shop2026!!", "business_name": "Old Shop"}, Response())
    t = S.db.tenants.find_one({"id": out["tenant_id"]})
    check("legacy → onboarding done + trial started", t["onboarding_status"] == "done"
          and t["subscription_status"] == "trialing")
    check("legacy trial is 28 days", t["trial_duration_days"] == 28)


def test_step2(u):
    print("\nStep 2 — /api/onboarding/company")
    tk = tok(u["email"], tenant_id=u["tenant_id"])
    expect_status("bad postal code → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "postal_code": "3700"}), None, tk))
    expect_status("13-digit SIRET → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "siret": "1234567890001"}), None, tk))
    expect_status("unknown sector → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "sector": "crypto"}), None, tk))
    out = OB.complete_company(OB.CompanyDetails(**STEP2), None, tk)
    t = S.db.tenants.find_one({"id": u["tenant_id"]})
    check("onboarding done", out["onboarding_status"] == "done" and t["onboarding_status"] == "done")
    check("trial started NOW for 28 days", t["subscription_status"] == "trialing"
          and t["trial_duration_days"] == 28 and out["trial"]["days_left"] in (27, 28))
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
    print("\nDay 27 — trial reminder via daily cron")
    tid = u["tenant_id"]
    now = datetime.now(timezone.utc)
    # Day 10 of 28: nothing should go out.
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": now + timedelta(days=18)},
                                           "$unset": {"trial_reminder_sent_at": ""}})
    r = OB.run_trial_reminders()
    check("day 10 → no email", r["reminders_sent"] == 0 and len(SENT) == 0)
    # Day 27: 1 day left → one email, then never again.
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": now + timedelta(hours=30)}})
    r = OB.run_trial_reminders()
    check("day 27 → exactly one email to the owner", r["reminders_sent"] == 1 and SENT[-1]["to"][0]["email"] == "marie@cafe.fr")
    check("email is in French and links to billing", "se termine" in SENT[-1]["htmlContent"]
          and "settings?tab=billing" in SENT[-1]["htmlContent"])
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


if __name__ == "__main__":
    u = test_step1()
    test_step2(u)
    test_reminder(u)
    test_legacy_register()
    test_oauth()
    _patch.stop()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)
