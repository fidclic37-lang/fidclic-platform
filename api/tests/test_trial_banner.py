"""
« Masquer » on the trial banner (user, 2026-10-16: « cross dabaate hai toh hat
jaata hai, lekin page refresh krne k baad fir se aa jaata hai »).

The quiet pill's cross is now kept on the ACCOUNT, so it holds after a refresh
and on every device the owner uses. The reminder and the expired banner carry
no cross and must never be silenced by it. A trial that starts later is a new
trial: its countdown shows again.

Run: cd api && /usr/local/bin/python3 tests/test_trial_banner.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-trial-banner")
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
                           "trial_started_at": now - timedelta(days=5),
                           "trial_ends_at": now + timedelta(days=25)})
    db.users.insert_one({"email": "marie@cafe.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    db.users.insert_one({"email": "paul@cafe.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    MARIE = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "marie@cafe.fr", "role": "business_owner", "tenant_id": "t1"})}
    PAUL = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "paul@cafe.fr", "role": "business_owner", "tenant_id": "t1"})}

    def state(h=None):
        return http("GET", "/api/owner/trial-status", headers=h or MARIE).json()

    print("\n« Masquer » holds after a refresh, and on the owner's other devices")
    st = state()
    check(f"day 5 of 30 → the quiet pill ({st['days_left']} days left)",
          st["is_in_trial"] and not st["reminder_window"] and st["banner_hidden"] is False)
    r = http("POST", "/api/owner/trial-status/hide-banner", headers=MARIE)
    check(f"the cross is accepted ({r.status_code})", r.status_code == 200 and r.json()["banner_hidden"] is True)
    check("refreshing the page: still hidden", state()["banner_hidden"] is True)
    check("her other phone: hidden too (it is kept on the account)",
          state()["banner_hidden"] is True)
    check("another account of the same shop still sees it",
          state(PAUL)["banner_hidden"] is False)

    print("\nWhat « Masquer » must NOT silence")
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_ends_at": now + timedelta(hours=20)}})
    st = state()
    check("the last-day reminder is still reported (its banner has no cross)",
          st["reminder_window"] is True and st["is_expired"] is False)
    # its very last day — « se termine aujourd'hui » — is the reminder too
    # (2026-10-24: days_left 0 fell outside the window and the banner vanished)
    from zoneinfo import ZoneInfo
    paris = ZoneInfo("Europe/Paris")
    p_now = datetime.now(timezone.utc).astimezone(paris)
    end_today = min(p_now.replace(hour=23, minute=59, second=0, microsecond=0), p_now + timedelta(minutes=30)) \
        if p_now.hour < 23 or p_now.minute < 30 else p_now + timedelta(minutes=10)
    if end_today.date() == p_now.date():
        db.tenants.update_one({"id": "t1"}, {"$set": {"trial_ends_at": end_today.astimezone(timezone.utc)}})
        st = state()
        check(f"the last day (days_left {st['days_left']}): the reminder, not nothing",
              st["days_left"] == 0 and st["reminder_window"] is True and st["is_expired"] is False)
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_ends_at": now - timedelta(hours=2)}})
    check("an expired trial is still reported", state()["is_expired"] is True)

    print("\nA trial that starts later is a new trial")
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_started_at": now + timedelta(seconds=5),
                                                  "trial_ends_at": now + timedelta(days=30)}})
    check("its countdown shows again", state()["banner_hidden"] is False)

    print("\nWho may hide it")
    check("the endpoint is not a page permission (common to every account)",
          RP.is_common("/api/owner/trial-status/hide-banner", "POST"))
    check("…and reading the countdown stays a common read",
          RP.is_common("/api/owner/trial-status", "GET"))
    db.users.insert_one({"email": "staff@cafe.fr", "role": "staff", "tenant_id": "t1", "active": True})
    STAFF = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "staff@cafe.fr", "role": "staff", "tenant_id": "t1"})}
    check("a staff account cannot hide it",
          http("POST", "/api/owner/trial-status/hide-banner", headers=STAFF).status_code in (401, 403))
    check("and nobody can without a token",
          http("POST", "/api/owner/trial-status/hide-banner").status_code in (401, 403))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
