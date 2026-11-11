"""
The « essai terminé » banner can be closed for good (user, 2026-11-11: « jo
message dikha rha… agar woh hatata hai toh fir dikhna band ho jaaye »).

Nothing is locked when a trial ends (the same day: « kuch mat band karo »):
the banner only says so. Its cross is kept on the ACCOUNT (a refresh, another
device), apart from the quiet pill's — closing one never silences the other —
and a later trial that ends again shows it again.

Run: cd api && python3 tests/test_trial_expired_banner.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-trial-expired")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    from features import role_perms as RP

    db = server.db
    now = datetime.now(timezone.utc)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "lumiere", "name": "Café Lumière", "plan": "vip",
                           "subscription_status": "trialing", "is_active": True,
                           "trial_started_at": now - timedelta(days=32),
                           "trial_ends_at": now - timedelta(days=2)})
    for e, role in (("marie@cafe.fr", "business_owner"), ("paul@cafe.fr", "business_owner"),
                    ("staff@cafe.fr", "staff")):
        db.users.insert_one({"email": e, "role": role, "tenant_id": "t1", "active": True})
    tok = lambda e, role="business_owner": {"Authorization": "Bearer " + auth.create_access_token(  # noqa: E731
        {"sub": e, "role": role, "tenant_id": "t1"})}
    MARIE, PAUL, STAFF = tok("marie@cafe.fr"), tok("paul@cafe.fr"), tok("staff@cafe.fr", "staff")
    HIDE = "/api/owner/trial-status/hide-expired-banner"

    def state(h=None):
        return http("GET", "/api/owner/trial-status", headers=h or MARIE).json()

    print("\nAn ended trial: told, nothing locked")
    st = state()
    check("the trial is reported ended", st["is_expired"] is True)
    check("its banner is shown at first", st["expired_banner_hidden"] is False)
    check("the plan is left as it was (Pro IA)", db.tenants.find_one({"id": "t1"})["plan"] == "vip")

    print("\nThe cross holds")
    r = http("POST", HIDE, headers=MARIE)
    check(f"the cross is accepted ({r.status_code})", r.status_code == 200 and r.json()["expired_banner_hidden"] is True)
    check("a refresh: still hidden", state()["expired_banner_hidden"] is True)
    check("another account of the shop still sees it (kept per account)", state(PAUL)["expired_banner_hidden"] is False)
    check("closing it changes nothing else: still ended, still the same plan",
          state()["is_expired"] is True and db.tenants.find_one({"id": "t1"})["plan"] == "vip")

    print("\nThe two crosses are apart")
    r = http("POST", "/api/owner/trial-status/hide-banner", headers=PAUL)
    check("hiding the quiet pill does not hide the ended banner", state(PAUL)["expired_banner_hidden"] is False)
    check("hiding the ended banner does not hide the quiet pill", state()["banner_hidden"] is False)

    print("\nA later trial that ends again is told again")
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_started_at": now + timedelta(seconds=1),
                                                  "trial_ends_at": now + timedelta(days=30)}})
    check("while it runs, nothing ended to hide", state()["is_expired"] is False)
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_ends_at": now + timedelta(seconds=2)}})
    import time
    time.sleep(2.5)
    st = state()
    check("once it ends, its banner shows again", st["is_expired"] is True and st["expired_banner_hidden"] is False)

    print("\nWho may close it")
    check("common to every account (no page permission)", RP.is_common(HIDE, "POST"))
    check("a staff account cannot", http("POST", HIDE, headers=STAFF).status_code in (401, 403))
    check("nobody without a token", http("POST", HIDE).status_code in (401, 403))
    db.tenants.insert_one({"id": "t2", "name": "Payé", "plan": "gold", "subscription_status": "active"})
    db.users.insert_one({"email": "o@paye.fr", "role": "business_owner", "tenant_id": "t2", "active": True})
    r = http("POST", HIDE, headers={"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@paye.fr", "role": "business_owner", "tenant_id": "t2"})})
    check("a paying shop: harmless, nothing to hide", r.status_code == 200 and r.json()["is_expired"] is False)

    print("\nThe screen")
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "components", "BillingBanner.jsx")).read()
    check("the ended banner has its cross", "hideExpired" in src and "isExpired && trial.expired_banner_hidden" in src)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
