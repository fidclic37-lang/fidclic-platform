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
    expect_status("bad postal code → 400", 400,
                  lambda: OB.complete_company(OB.CompanyDetails(**{**STEP2, "postal_code": "3700"}), None, tk))
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
    me = S.get_me(tok(u["email"], tenant_id=u["tenant_id"]))
    check("/me says plan (UI parks the owner on /onboarding/formule)", me["onboarding_status"] == "plan")
    st = OB.onboarding_status(tk)
    check("status exposes the trial plan + days", st["trial_plan"] == "vip" and st["trial_days"] == 30)
    S.db.tenants.update_one({"id": u["tenant_id"]}, {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(days=3)}})
    out = OB.start_trial(None, tk)
    t = S.db.tenants.find_one({"id": u["tenant_id"]})
    check("plan step → onboarding done, business live", out["onboarding_status"] == "done"
          and t["onboarding_status"] == "done" and t["is_active"] is True)
    check("trial runs on Pro AI (vip)", t["plan"] == "vip" and out["plan"] == "vip")
    check("trial started NOW for 30 days", t["subscription_status"] == "trialing"
          and t["trial_duration_days"] == 30 and out["trial"]["days_left"] in (29, 30))
    check("created_at = the day it went live", (datetime.now(timezone.utc) - (t["created_at"] if t["created_at"].tzinfo else t["created_at"].replace(tzinfo=timezone.utc))).total_seconds() < 60)
    ends0 = t["trial_ends_at"]
    OB.start_trial(None, tk)
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
    tid = u["tenant_id"]
    now = datetime.now(timezone.utc)
    # Day 10 of 30: nothing should go out.
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": now + timedelta(days=18)},
                                           "$unset": {"trial_reminder_sent_at": ""}})
    r = OB.run_trial_reminders()
    check("day 10 → no email", r["reminders_sent"] == 0 and len(SENT) == 0)
    # Day 29: 1 day left → one email, then never again.
    S.db.tenants.update_one({"id": tid}, {"$set": {"trial_ends_at": now + timedelta(hours=30)}})
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
    test_drafts()
    _patch.stop()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)
